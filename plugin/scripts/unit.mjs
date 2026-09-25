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

console.log("");
console.log("pathToFileUrl 已移除；frameBaseHref 的路径转换规则（预览靠 base + srcdoc）");
{
  check(
    "Windows 盘符路径补三个斜杠并以斜杠结尾",
    utils.frameBaseHref("E:\\InLoopHub\\dist\\a") === "file:///E:/InLoopHub/dist/a/",
    utils.frameBaseHref("E:\\InLoopHub\\dist\\a"),
  );
  check(
    "已经是 POSIX 绝对路径时补两个斜杠",
    utils.frameBaseHref("/home/u/dist/a") === "file:///home/u/dist/a/",
    utils.frameBaseHref("/home/u/dist/a"),
  );
  check(
    "已带尾斜杠时不重复",
    utils.frameBaseHref("E:/a/b/") === "file:///E:/a/b/",
    utils.frameBaseHref("E:/a/b/"),
  );
  check(
    "含空格与中文的目录原样保留",
    utils.frameBaseHref("E:/d/我的 目录") === "file:///E:/d/我的 目录/",
    utils.frameBaseHref("E:/d/我的 目录"),
  );
  check("结果一定以斜杠结尾（拼接相对路径必需）", utils.frameBaseHref("E:/a").endsWith("/"));
}

console.log("");
console.log("inlineImages（把图片内联成 data URI，绕过 Obsidian 的 file:// 限制）");
{
  // 一张最小的 1x1 PNG
  const png = new Uint8Array([
    0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a,
    0x00, 0x00, 0x00, 0x0d, 0x49, 0x48, 0x44, 0x52,
  ]);
  const files = new Map([
    ["E:/out/images/a.png", png],
    ["E:/out/images/屏幕 截图.png", png],
  ]);
  const readBinary = (p) => files.get(p) ?? null;

  const body = '<p>x</p><img src="images/a.png"><img src="https://ex.com/b.png">';

  const r1 = utils.inlineImages(body, "E:/out", readBinary);
  check("本地图片被换成 data URI", r1.html.includes("data:image/png;base64,"), r1.html.slice(0, 120));
  check("替换计数正确", r1.inlined === 1, String(r1.inlined));
  check("外链图片不动", r1.html.includes('src="https://ex.com/b.png"'));
  check("文字内容保留", r1.html.includes("<p>x</p>"));

  // src 是 URL，含空格与中文的路径必须先解码再当文件路径用
  const r2 = utils.inlineImages(
    '<img src="images/%E5%B1%8F%E5%B9%95%20%E6%88%AA%E5%9B%BE.png">',
    "E:/out",
    readBinary,
  );
  check("URL 编码的路径先解码再定位（含空格与中文）", r2.inlined === 1, String(r2.inlined));

  // 读不到时保留原样并计数，不该抛异常（少一张图也要把文字显示出来）
  const r3 = utils.inlineImages('<img src="images/none.png">', "E:/out", readBinary);
  check("读不到时保留原 src", r3.html.includes('src="images/none.png"'), r3.html);
  check("读不到时计入 skipped", r3.skipped === 1, String(r3.skipped));
  check("读不到时不抛异常", r3.inlined === 0);

  // 超过上限的图片跳过
  const big = new Uint8Array(utils.INLINE_IMAGE_LIMIT_BYTES + 1);
  const r4 = utils.inlineImages('<img src="images/big.png">', "E:/out", (p) =>
    p.endsWith("big.png") ? big : null,
  );
  check("超过体积上限的图片跳过（不撑爆 iframe）", r4.skipped === 1 && r4.inlined === 0);

  // data URI 与已有内联不该被二次处理
  const r5 = utils.inlineImages('<img src="data:image/png;base64,AAAA">', "E:/out", readBinary);
  check("已是 data URI 的不再处理", r5.inlined === 0 && r5.skipped === 0, r5.html);
}

console.log("");
console.log("base64FromBytes");
{
  // 用已知答案校验手写实现
  check("空数组 → 空串", utils.base64FromBytes(new Uint8Array([])) === "");
  check(
    "'M' (0x4D) → TQ==",
    utils.base64FromBytes(new Uint8Array([0x4d])) === "TQ==",
    utils.base64FromBytes(new Uint8Array([0x4d])),
  );
  check(
    "'Ma' → TWE=",
    utils.base64FromBytes(new Uint8Array([0x4d, 0x61])) === "TWE=",
    utils.base64FromBytes(new Uint8Array([0x4d, 0x61])),
  );
  check(
    "'Man' → TWFu",
    utils.base64FromBytes(new Uint8Array([0x4d, 0x61, 0x6e])) === "TWFu",
    utils.base64FromBytes(new Uint8Array([0x4d, 0x61, 0x6e])),
  );
  // 与 Buffer 对照（Node 环境有 Buffer，可作为参照实现）
  const sample = new Uint8Array([0, 1, 2, 253, 254, 255, 128, 64, 32]);
  check(
    "与 Buffer.toString('base64') 一致",
    utils.base64FromBytes(sample) === Buffer.from(sample).toString("base64"),
    utils.base64FromBytes(sample),
  );
}

console.log("");
console.log("mimeForPath");
{
  const cases = [
    ["a.png", "image/png"],
    ["a.JPG", "image/jpeg"],
    ["a.jpeg", "image/jpeg"],
    ["a.gif", "image/gif"],
    ["a.webp", "image/webp"],
    ["a.svg", "image/svg+xml"],
    ["a.unknown", "application/octet-stream"],
  ];
  for (const [name, expected] of cases) {
    check(`${name} → ${expected}`, utils.mimeForPath(name) === expected, utils.mimeForPath(name));
  }
}

rmSync(outDir, { recursive: true, force: true });

console.log("");
console.log(`结果：${passed} 通过 / ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
