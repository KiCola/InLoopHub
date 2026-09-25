/**
 * 与 Obsidian 宿主环境打交道的辅助函数。
 *
 * 集中在这里的原因：这两个操作都触碰 Obsidian 的类型边界——
 * `getBasePath()` 只存在于桌面版的 `FileSystemAdapter`，
 * 而 `electron` 模块在类型层面不在依赖里。分散写会让每个调用点
 * 各写一遍断言，且一旦宿主 API 变化要改多处。
 */

import type { App } from "obsidian";
import { stripHtml } from "./preview-utils";

/** 只声明我们用到的部分，避免依赖 obsidian 包是否导出 FileSystemAdapter */
interface AdapterWithBasePath {
  getBasePath?: () => string;
}

/**
 * 取 vault 在磁盘上的绝对路径。
 *
 * 桌面版的适配器有 `getBasePath()`；移动版没有（本插件声明为桌面专用，
 * 因此正常情况一定拿得到）。拿不到时返回空串，由调用方决定怎么提示——
 * 拼出一个错误的路径比返回空更糟。
 */
export function vaultBasePath(app: App): string {
  const adapter = app.vault.adapter as unknown as AdapterWithBasePath;
  if (typeof adapter.getBasePath !== "function") return "";
  return (adapter.getBasePath() ?? "").replace(/\\/g, "/");
}

/** 把绝对路径转成 vault 内的相对路径；不在 vault 内时返回 null */
export function toVaultPath(app: App, absolutePath: string): string | null {
  const base = vaultBasePath(app);
  const normalized = absolutePath.replace(/\\/g, "/");
  if (!base || !normalized.startsWith(base + "/")) return null;
  return normalized.slice(base.length + 1);
}

/**
 * 用系统默认程序打开一个文件。
 *
 * `electron` 由宿主提供，esbuild 已把它标为 external，因此运行时能 require 到；
 * 类型层面它不在依赖里，所以这里做一次局部声明。
 */
export async function openWithSystem(path: string): Promise<void> {
  const electron = require("electron") as {
    shell?: { openPath: (target: string) => Promise<string> };
  };
  if (!electron.shell) {
    throw new Error("当前环境没有 electron.shell，无法用系统程序打开文件。");
  }
  await electron.shell.openPath(path);
}

/**
 * 读一个二进制文件；失败时返回 null（调用方自行降级）。
 *
 * 与 :func:`readTextFile` 的区别：图片内联进预览时"读不到"不该中断整个预览——
 * 少一张图仍应把文字显示出来，因此这里不抛异常。
 */
export function readBinaryFile(path: string): Uint8Array | null {
  try {
    const fs = require("node:fs") as {
      readFileSync?: (target: string) => Uint8Array;
    };
    if (typeof fs.readFileSync !== "function") return null;
    return fs.readFileSync(path);
  } catch {
    return null;
  }
}

/**
 * 读一个文本文件；失败时**抛出带原因的异常**。
 *
 * 为什么不返回 `null` 表示失败：那样调用方只能说"读不到产物"，
 * 而**看不到为什么**——是文件不存在、路径不对、还是权限不够。
 * 这个诊断信息缺失让一个真实的 bug 排查了很久（AGENTS.md §4：不静默失败、
 * 错误信息要说清「哪里错了 + 为什么 + 怎么改」）。
 *
 * 用 `require("node:fs")` 而不是 `await import(...)`：本插件的产物是
 * CommonJS 包，`require` 是已验证可用的路径（`require("electron")` 同理）。
 */
export function readTextFile(path: string): string {
  const fs = require("node:fs") as {
    readFileSync?: (target: string, encoding: string) => string;
    existsSync?: (target: string) => boolean;
  };

  if (typeof fs.readFileSync !== "function") {
    throw new Error(
      "当前环境拿不到 Node 的文件读取能力（require('node:fs') 不可用）。\n" +
        "这属于插件与宿主环境不兼容，请反馈这条信息。",
    );
  }

  if (fs.existsSync && !fs.existsSync(path)) {
    throw new Error(
      `文件不存在：${path}\n` +
        "可能是构建没有真正产出，或两次构建之间文件被清理了。\n" +
        "修正方法：先单独点一次「构建并复制」，看是否报错。",
    );
  }

  try {
    return fs.readFileSync(path, "utf8");
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `读取文件失败：${path}\n原因：${detail}\n` +
        "若提示权限不足，检查该目录是否被同步盘客户端锁定。",
    );
  }
}


/** 剪贴板写入的结果，用于告诉用户"样式到底写进去了没有" */
export interface ClipboardOutcome {
  /** 是否写入了 HTML flavor（微信排版靠它） */
  wroteHtml: boolean;
  /** 写入方式，供诊断与提示 */
  method: "electron" | "navigator-text-only";
}

/**
 * 把正文放进剪贴板，**同时写 HTML 与纯文本两种 flavor**。
 *
 * 为什么不能用 `navigator.clipboard.writeText()`：
 * 它只写 `text/plain` 一个 flavor，而**微信编辑器是通过 `text/html` 取得内联样式的**。
 * 只用 writeText 的话，粘进公众号会丢掉全部排版——那正是这个插件的旗舰功能。
 *
 * 因此优先用 Electron 的原生剪贴板（可一次写多个 flavor）。
 * 拿不到时降级为纯文本，并**明确告知用户样式未写入**——
 * 静默降级会让人以为"工具就是这样"，而实际是排版丢了。
 */
export async function copyRichText(html: string): Promise<ClipboardOutcome> {
  const electron = require("electron") as {
    clipboard?: { write: (data: { html?: string; text?: string }) => void };
  };

  // 纯文本兜底用去标签后的内容，便于粘到不支持 HTML 的地方时仍可读。
  // stripHtml 与预览模块共用同一实现，避免两处漂移。
  const plain = stripHtml(html);

  if (electron.clipboard && typeof electron.clipboard.write === "function") {
    electron.clipboard.write({ html, text: plain });
    return { wroteHtml: true, method: "electron" };
  }

  await navigator.clipboard.writeText(plain);
  return { wroteHtml: false, method: "navigator-text-only" };
}
