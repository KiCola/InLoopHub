/**
 * 冒烟测试：插件的 CLI 调用层能否真的驱动 Python 内核。
 *
 * 为什么需要它：插件与内核之间只有 JSON 契约这一层粘合，
 * 而这一层出错的方式很隐蔽——域名对不上、参数顺序错、错误码没透传。
 * 这些在 TypeScript 类型层面看不出来，只有在真机上跑一次才知道。
 *
 * 运行：node scripts/smoke.mjs
 * 前置：工具仓库已装好（.venv/Scripts/inloop.exe 可用）
 *
 * 它**不加载 Obsidian**（插件类需要宿主），只测 cli.ts 这一层。
 */

import { build } from "esbuild";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repoRoot = resolve(root, "..");

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

// 把 cli.ts 单独打包成可在 Node 里 import 的 ESM（它不依赖 obsidian）
const outfile = join(root, "dist", "smoke-cli.mjs");
await build({
  entryPoints: [join(root, "src/inloop/cli.ts")],
  outfile,
  bundle: true,
  format: "esm",
  platform: "node",
  target: "node22",
  external: ["obsidian"],
  logLevel: "error",
});

const cli = await import(`file://${outfile.replace(/\\/g, "/")}`);

const executable = join(repoRoot, ".venv", "Scripts", "inloop.exe");
const examplesRoot = join(repoRoot, "examples");

// 造一个独立的内容目录，避免依赖 examples/
const tempContent = mkdtempSync(join(tmpdir(), "inloop-plugin-smoke-"));
const articleDir = join(tempContent, "2026", "001-smoke");
mkdirSync(articleDir, { recursive: true });

// 封面必须存在，否则构建会因 IMG003 中止。
// 写一个最小的合法 PNG（1x1 透明），够 cover 检查通过即可。
const onePixelPng = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg==",
  "base64",
);
writeFileSync(join(articleDir, "cover.png"), onePixelPng);

writeFileSync(
  join(articleDir, "index.md"),
  [
    "---",
    "id: 1",
    'title: "冒烟测试文章"',
    'slug: "smoke"',
    "date: 2026-09-25",
    'author: "测试"',
    'category: "paper"',
    'status: "draft"',
    "tags:",
    "  - 测试",
    'summary: "冒烟测试。"',
    'cover: "cover.png"',
    "platforms:",
    "  wechat: true",
    "---",
    "",
    "# 冒烟测试文章",
    "",
    "## 01 · 第一节",
    "",
    "正文段落。",
    "",
  ].join("\n"),
  "utf8",
);

console.log("插件 CLI 层冒烟测试");
console.log(`  可执行文件：${executable}`);
console.log(`  内容目录：${tempContent}`);
console.log("");

// 1) 自动探测可执行文件
const guessed = cli.guessExecutable("", repoRoot);
check("能从工具仓库探测到 inloop", guessed.endsWith("inloop.exe") || guessed.endsWith("inloop"), guessed);

const options = { executable: guessed, contentRoot: tempContent, repoRoot };

// 2) list：应看到刚造的文章，且路径是相对形式
try {
  const listed = await cli.listArticles(options);
  check("list 返回合法信封", listed.ok === true && listed.schema === 1);
  check("list 找到 1 篇文章", listed.articles?.length === 1, `实际 ${listed.articles?.length}`);
  const article = listed.articles?.[0];
  check("标题正确", article?.title === "冒烟测试文章", article?.title);
  check("正文路径是相对形式", article?.path === "2026/001-smoke/index.md", article?.path);
  check("content_root 是绝对路径", /^[A-Za-z]:\//.test(listed.content_root ?? ""), listed.content_root);
} catch (error) {
  check("list 调用成功", false, String(error));
}

// 3) check：逐篇校验
try {
  const checked = await cli.checkArticle(options, "001-smoke");
  check("check 通过且无 ERROR", checked.error_count === 0, `ERROR=${checked.error_count}`);
} catch (error) {
  check("check 调用成功", false, String(error));
}

// 4) build：构建并拿到可直接读取的产物路径
let buildResult = null;
try {
  buildResult = await cli.buildArticle(options, "001-smoke");
  check("build 成功", buildResult.ok === true);
  check("html_path 存在", buildResult.html_path?.length > 0, buildResult.html_path);
  const { existsSync } = await import("node:fs");
  check("html 文件真的落盘", existsSync(buildResult.html_path), buildResult.html_path);
} catch (error) {
  check("build 调用成功", false, String(error));
}

// 5) 错误映射：找不到文章应抛带具体错误码的 InloopError
try {
  await cli.checkArticle(options, "no-such-article");
  check("找不到文章时抛错", false, "没有抛错");
} catch (error) {
  const isInloopError = error instanceof cli.InloopError;
  check("抛的是 InloopError", isInloopError, error?.constructor?.name);
  check("错误码为 article_not_found", error?.code === "article_not_found", error?.code);
  check("带有修正建议", typeof error?.hint === "string" && error.hint.length > 0);
  const display = typeof error?.toDisplay === "function" ? error.toDisplay() : "";
  check("toDisplay 给出多行说明", display.includes("\n"), JSON.stringify(display.slice(0, 60)));
}

// 6) 可执行文件不存在时给出可操作的指引
try {
  await cli.listArticles({ ...options, executable: "definitely-not-a-real-binary-xyz" });
  check("可执行文件不存在时抛错", false, "没有抛错");
} catch (error) {
  check("错误码为 cli_not_found", error?.code === "cli_not_found", error?.code);
  check("提示指向插件设置", (error?.hint ?? "").includes("设置"), error?.hint);
}

// 清理。
// 注意：只在真的拿到产物目录时才删它——写成 `rmSync(x ?? "")` 会在
// 值为空时把路径解析成当前目录，把插件目录本身删掉（第一版真这么写过）。
rmSync(tempContent, { recursive: true, force: true });
if (buildResult?.output_dir) {
  rmSync(buildResult.output_dir, { recursive: true, force: true });
}
rmSync(outfile, { force: true });

console.log("");
console.log(`结果：${passed} 通过 / ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
