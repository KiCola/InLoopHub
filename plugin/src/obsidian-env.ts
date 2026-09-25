/**
 * 与 Obsidian 宿主环境打交道的辅助函数。
 *
 * 集中在这里的原因：这两个操作都触碰 Obsidian 的类型边界——
 * `getBasePath()` 只存在于桌面版的 `FileSystemAdapter`，
 * 而 `electron` 模块在类型层面不在依赖里。分散写会让每个调用点
 * 各写一遍断言，且一旦宿主 API 变化要改多处。
 */

import type { App } from "obsidian";

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
