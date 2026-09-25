/**
 * 纯函数单测。
 *
 * 覆盖范围正是**独立审核指出的盲区**：上一轮 M3 有两个阻塞缺陷
 * （预览图片全坏、复制丢排版）都落在预览与剪贴板这一层，
 * 而当时的冒烟测试只覆盖了 CLI 层，一条都没测到。
 *
 * 这些函数现在抽在 `src/preview-utils.ts` 里，不依赖 Obsidian，
 * 因此可以在 Node 里直接调用真实实现——而不是去断言源码文本
 * （那种测试改一行格式就会坏，没有价值）。
 *
 * 运行：node scripts/unit.mjs
 */

import { build } from "esbuild";
import { rmSync } from "node:fs";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = join(root, "dist", "unit");

let passed = 0;
let failed = 0;

function check(label, ok, detail = "") {
  if (ok) {
    passed += 1;
    console.log(`  ✓ ${label}`);
  } else {
    failed += 1;
    console.log(`  ✗ ${label}${detail ? `　${detail}` : ""}`);
  }
}

const outfile = join(outDir, "preview-utils.mjs");
await build({
  entryPoints: [join(root, "src/preview-utils.ts")],
  outfile,
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node22",
  logLevel: "error",
});
const utils = await import(`file://${outfile.replace(/\\/g, "/")}`);

console.log("纯函数单测（预览与剪贴板）");
console.log("");

// --- 阻塞 1 的成因：预览图片不显示 ---
console.log("frameBaseHref（图片能否找到）");
{
  check(
    "Windows 路径转成 file:// 形式",
    utils.frameBaseHref("E:\\InLoopHub\\dist\\wechat\\001-x") ===
      "file:///E:/InLoopHub/dist/wechat/001-x/",
    utils.frameBaseHref("E:\\InLoopHub\\dist\\wechat\\001-x"),
  );
  check(
    "POSIX 路径同样处理",
    utils.frameBaseHref("/home/u/inloop/dist/001-x") === "file:///home/u/inloop/dist/001-x/",
    utils.frameBaseHref("/home/u/inloop/dist/001-x"),
  );
  check(
    "已带尾斜杠时不重复",
    utils.frameBaseHref("E:/a/b/") === "file:///E:/a/b/",
    utils.frameBaseHref("E:/a/b/"),
  );
  check("结果以斜杠结尾（拼接相对路径必需）", utils.frameBaseHref("E:/a").endsWith("/"));
}

console.log("");
console.log("wrapForFrame（base 与 sandbox 都要正确）");
{
  const html = utils.wrapForFrame("<p>正文</p>", "file:///E:/a/b/");
  check("插入了 <base href>", html.includes('<base href="file:///E:/a/b/">'));
  check("base 在 head 内、body 之前", html.indexOf("<base") < html.indexOf("<body>"));
  check("保留了正文", html.includes("<p>正文</p>"));
  check("声明了 utf-8（中文必需）", html.includes('charset="utf-8"'));
  check("没有引入外部资源", !/<link|<script/i.test(html));

  // 这两条是阻塞 1 的核心：sandbox 为空会让所有 file:// 图片加载失败
  check(
    "sandbox 不是空串（空串 = 图片全坏）",
    utils.FRAME_SANDBOX.length > 0,
    JSON.stringify(utils.FRAME_SANDBOX),
  );
  check(
    "sandbox 含 allow-same-origin（允许本地文件）",
    utils.FRAME_SANDBOX.includes("allow-same-origin"),
    utils.FRAME_SANDBOX,
  );
  check(
    "sandbox 不含 allow-scripts（不授予脚本权限）",
    !utils.FRAME_SANDBOX.includes("allow-scripts"),
    utils.FRAME_SANDBOX,
  );
}

console.log("");
console.log("extractBodyHtml（粘进剪贴板的是什么）");
{
  const full = "<!DOCTYPE html><html><head><title>t</title></head><body><p>x</p></body></html>";
  check("取出 body 内容", utils.extractBodyHtml(full) === "<p>x</p>", utils.extractBodyHtml(full));
  check("丢掉 DOCTYPE 与 head", !utils.extractBodyHtml(full).includes("DOCTYPE"));
  check("没有 body 时退回原文", utils.extractBodyHtml("<p>y</p>") === "<p>y</p>");
  check("body 带属性时也能取", utils.extractBodyHtml('<body class="a">z</body>') === "z");
}

console.log("");
console.log("stripHtml（剪贴板的纯文本兜底）");
{
  const html = '<p>第一段</p><p>带<strong>加粗</strong>的文字</p><pre>a = 1\nb = 2</pre>';
  const text = utils.stripHtml(html);
  check("去掉了所有标签", !/[<>]/.test(text), text);
  check("保留了文字内容", text.includes("第一段") && text.includes("加粗"), text);
  check("块级元素处产生换行", text.split("\n").length >= 2, JSON.stringify(text));
  check("实体被还原", utils.stripHtml("a &amp; b &lt;c&gt;").includes("a & b <c>"));
  check("连续空行被压缩", !/\n{3,}/.test(utils.stripHtml("<p>a</p><p></p><p></p><p>b</p>")));
  check("br 变成换行", utils.stripHtml("a<br>b").includes("a\nb"));
  check("首尾空白被去掉", utils.stripHtml("  <p>x</p>  ") === "x");
}

rmSync(outDir, { recursive: true, force: true });

console.log("");
console.log(`结果：${passed} 通过 / ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
