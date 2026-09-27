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
import { readFileSync, rmSync, writeFileSync } from "node:fs";
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

/** 把某个源文件单独打包成可在 Node 里 import 的模块（宿主模块保持外部） */
async function bundle(entry, name, plugins = []) {
  const target = join(outDir, name);
  await build({
    entryPoints: [join(root, entry)],
    outfile: target,
    bundle: true,
    // **用 CommonJS**：源码里有 `require("node:crypto")` 这类调用，
    // 而 esbuild 在 ESM 输出下会把 require 变成"动态 require 不支持"。
    // 插件真实产物也是 CJS，保持一致才测的是同一条路径。
    format: "cjs",
    platform: "node",
    target: "node22",
    // obsidian 与 electron 都由宿主提供，不进 bundle
    external: ["obsidian", "electron"],
    logLevel: "error",
    plugins,
  });
  // CJS 用 createRequire 载入，import() 也能拿到 default
  const loaded = await import(`file://${target.replace(/\\/g, "/")}`);
  return loaded.default ?? loaded;
}

const utils = await bundle("src/preview-utils.ts", "preview-utils.cjs");

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

console.log("");
console.log("contentHash（必须与 Python 的 inloop.build.content_hash 一致）");
{
  // contentHash 在 obsidian-env.ts 里（它要用 node:crypto），单独打包
  const env = await bundle("src/obsidian-env.ts", "env-hash.cjs");
  check("空串的哈希长度是 16", env.contentHash("").length === 16, env.contentHash(""));
  check("同一输入结果稳定", env.contentHash("abc") === env.contentHash("abc"));
  check("不同输入结果不同", env.contentHash("abc") !== env.contentHash("abd"));
  // SHA-256("") 的前 16 位，用定义值校验实现没写错
  check(
    "空串哈希与 SHA-256 定义一致",
    env.contentHash("") === "e3b0c44298fc1c14",
    env.contentHash(""),
  );
  check(
    "中文内容也能算出 16 位十六进制",
    /^[0-9a-f]{16}$/.test(env.contentHash("第一篇测试\n\n正文。")),
    env.contentHash("第一篇测试\n\n正文。"),
  );
}

console.log("");
console.log("contentPathToVault（内容目录可能是接进 vault 的目录联接）");
{
  const env = await bundle("src/obsidian-env.ts", "env-path.cjs");

  // 造一个最小 app：vault 根 + 若干根目录 + 模拟"联接点解析真实路径"
  const VAULT = "C:/Users/zzr/Nutstore/1/我的坚果云/obsidian/TechTree";
  const app = {
    vault: {
      adapter: {
        getBasePath: () => "C:\\Users\\zzr\\Nutstore\\1\\我的坚果云\\obsidian\\TechTree",
        // 模拟真实的目录联接：InLoopContent 的真实位置是 E:/InLoopHub/content
        realpath: (p) =>
          p === "InLoopContent"
            ? "E:\\InLoopHub\\content"
            : `C:\\Users\\zzr\\Nutstore\\1\\我的坚果云\\obsidian\\TechTree\\${p}`,
      },
      getRoot: () => ({
        children: [
          { name: "InLoopContent", children: [] },
          { name: "InLoopPub", children: [] },
          { name: "研究卡片", children: [] },
          { name: "某篇笔记.md" }, // 文件没有 children，应被过滤
        ],
      }),
      getAbstractFileByPath: (p) => (p ? { path: p } : null),
    },
  };

  check(
    "内容目录在 vault 内：直接算相对路径",
    env.contentPathToVault(app, `${VAULT}/InLoopContent`, "2026/002-try/index.md") ===
      "InLoopContent/2026/002-try/index.md",
    env.contentPathToVault(app, `${VAULT}/InLoopContent`, "2026/002-try/index.md"),
  );

  // 这是本机真实情况：Python 解引用了联接，报的是 vault 外的真实路径
  check(
    "内容目录是 vault 外真实路径：按末段名字找回联接点",
    env.contentPathToVault(app, "E:/InLoopHub/content", "2026/002-try/index.md") ===
      "InLoopContent/2026/002-try/index.md",
    env.contentPathToVault(app, "E:/InLoopHub/content", "2026/002-try/index.md"),
  );

  check(
    "反斜杠与尾斜杠都能处理",
    env.contentPathToVault(
      app,
      "C:\\Users\\zzr\\Nutstore\\1\\我的坚果云\\obsidian\\TechTree\\InLoopContent\\",
      "2026/x/index.md",
    ) === "InLoopContent/2026/x/index.md",
  );

  check(
    "不给相对路径时只返回目录",
    env.contentPathToVault(app, `${VAULT}/InLoopPub`) === "InLoopPub",
    env.contentPathToVault(app, `${VAULT}/InLoopPub`),
  );

  check(
    "vault 外且找不到同名目录 → null（由调用方给出指引）",
    env.contentPathToVault(app, "D:/somewhere/else", "a/index.md") === null,
    String(env.contentPathToVault(app, "D:/somewhere/else", "a/index.md")),
  );
}

// 只替代宿主提供的类；文章识别与活动文件回退运行插件的真实实现。
const hostPlugins = [{
  name: "obsidian-test-host",
  setup(builder) {
    builder.onResolve({ filter: /^obsidian$/ }, () => ({ path: "obsidian", namespace: "test-host" }));
    builder.onLoad({ filter: /.*/, namespace: "test-host" }, () => ({
      contents: `export class Plugin {}
        export class PluginSettingTab {}
        export class ItemView { constructor(leaf) { this.app = leaf.app; this.contentEl = leaf.contentEl; } }
        export const MarkdownView = globalThis.TestMarkdownView ?? class {};
        export class TFile {}
        export class Notice { hide() {} }
        export class Setting {}
        export const normalizePath = p => p;
        export const debounce = fn => fn;
        export const setIcon = () => {};`,
      loader: "js",
    }));
  },
}];
const pluginModule = await bundle("src/main.ts", "main.cjs", hostPlugins);
console.log("预览默认定位右侧栏");
{
  const plugin = new pluginModule.default();
  const rightRoot = {};
  let detached = false;
  let revealed = null;
  let created = 0;
  let existing = [];
  const old = { getRoot: () => ({}), detach: () => { detached = true; } };
  const side = { getRoot: () => rightRoot, setViewState: async () => {} };
  plugin.app = { workspace: {
    rightSplit: rightRoot,
    getLeavesOfType: () => existing,
    getRightLeaf: () => { created += 1; return side; },
    getMostRecentLeaf: () => { throw new Error("不应创建中间分屏"); },
    revealLeaf: async leaf => { revealed = leaf; },
  } };
  plugin.refreshPreview = () => {};
  try {
    await plugin.activatePreview();
    check("默认在右侧栏新建面板", created === 1 && revealed === side);
  } catch (error) { check("默认在右侧栏新建面板", false, String(error)); }
  existing = [old];
  try {
    await plugin.activatePreview();
    check("原中间面板迁到侧栏且只保留一个", detached && revealed === side);
  } catch (error) { check("原中间面板迁到侧栏且只保留一个", false, String(error)); }
  existing = [side];
  const count = created;
  await plugin.activatePreview();
  check("再次打开复用右侧栏，不重复创建", created === count);
}
console.log("文章重命名后的识别与面板焦点回退");
{
  const plugin = new pluginModule.default();
  const file = {
    name: "index.md", extension: "md",
    path: "InLoopContent/2026/004-gpt6/index.md", parent: { name: "004-gpt6" },
  };
  let activeFile = file;
  plugin.settings.contentRoot = "C:/vault/InLoopContent";
  plugin.app = {
    vault: { adapter: { getBasePath: () => "C:/vault" } },
    workspace: {
      getActiveFile: () => activeFile,
      getMostRecentLeaf: () => ({ view: {} }),
      getLeavesOfType: () => [{ view: { file } }],
    },
  };
  check("小写正文可选中", plugin.activeSlug() === "004-gpt6");
  file.name = "GPT6.md";
  file.path = "InLoopContent/2026/004-gpt6/GPT6.md";
  check("任意文件名不作为正文入口", plugin.activeSlug() === "");
  file.name = "Index.md";
  file.path = "InLoopContent/2026/004-gpt6/Index.md";
  check("Windows 改回 Index.md 后恢复选中", plugin.activeSlug() === (process.platform === "win32" ? "004-gpt6" : ""));
  activeFile = null;
  check("点击面板后仍找到 Index.md 正文", plugin.activeSlug() === (process.platform === "win32" ? "004-gpt6" : ""));
  file.name = "index.md";
  file.path = "Other/2026/004-gpt6/index.md";
  check("内容目录外的正文不被识别", plugin.activeSlug() === "");
}

console.log("当前文章与产物必须绑定");
{
  const plugin = new pluginModule.default();
  const article = (slug) => ({ name: "index.md", extension: "md",
    path: `InLoopContent/2026/${slug}/index.md`, parent: { name: slug } });
  const a = article("001-a");
  const b = article("002-b");
  let active = a;
  plugin.settings.contentRoot = "C:/vault/InLoopContent";
  plugin.app = {
    vault: { adapter: { getBasePath: () => "C:/vault" } },
    workspace: {
      getActiveFile: () => active,
      getMostRecentLeaf: () => ({ view: {} }),
      getLeavesOfType: () => [{ view: { file: a } }, { view: { file: b } }],
    },
  };
  plugin.activeSlug();
  active = b;
  plugin.activeSlug();
  active = null;
  check("面板失焦后保留 B，不回退到列表第一篇 A", plugin.activeSlug() === "002-b");
  plugin.lastBuild = { metadata: { slug: "001-a" } };
  check("当前 B 不得取出 A 的旧产物", plugin.getLastBuild() === null);
  b.name = "改名.md";
  b.path = "InLoopContent/2026/002-b/改名.md";
  check("当前正文改名后不能偷偷选中 A", plugin.activeSlug() === "");
  check("改名后提供恢复 index.md 的提示", plugin.articleHint?.().includes("index.md") === true);
}

// 最小宿主 DOM：只提供视图实际调用的元素操作，不替代业务方法。
class TestElement {
  children = [];
  style = {};
  attrs = {};
  text = "";
  createEl(tag, options = {}) {
    const child = new TestElement();
    child.tag = tag;
    child.text = options.text ?? "";
    child.cls = options.cls ?? "";
    this.children.push(child);
    return child;
  }
  createDiv(options) { return this.createEl("div", options); }
  createSpan(options) { return this.createEl("span", options); }
  empty() { this.children = []; this.text = ""; }
  setText(text) { this.text = text; }
  toggleClass() {}
  addClass() {}
  setAttribute(key, value) { this.attrs[key] = value; }
  appendChild(child) { this.children.push(child); }
  remove() {}
  hide() {}
  show() {}
  allText() { return this.text + this.children.map(c => c.allText()).join(" "); }
}
globalThis.createDiv = (options) => new TestElement().createDiv(options);
const styleModule = await bundle("src/styles.ts", "styles.cjs");
{
  const existingStyle = { textContent: "旧插件样式" };
  globalThis.document = { getElementById: () => existingStyle };
  styleModule.installStyles();
  check("重载插件时更新已有样式", existingStyle.textContent !== "旧插件样式");
  delete globalThis.document;
}
const viewModule = await bundle("src/view.ts", "view.cjs", hostPlugins);
console.log("文章列表操作与异步预览");
{
  const file = { path: "InLoopContent/2026/002-b/index.md" };
  let opened = null;
  let selected = null;
  const centerRoot = {};
  let openState;
  const editorLeaf = { getRoot: () => centerRoot, openFile: async (target, state) => { opened = target; openState = state; } };
  const sidebarEditor = { getRoot: () => ({}), openFile: async () => { throw new Error("不能在侧栏编辑文章"); } };
  const app = {
    vault: {
      adapter: { getBasePath: () => "C:/vault" },
      getAbstractFileByPath: () => file,
    },
    workspace: {
      rootSplit: centerRoot,
      getMostRecentLeaf: () => editorLeaf,
      getLeavesOfType: () => [sidebarEditor, editorLeaf],
      getLeaf: () => { throw new Error("不应将预览面板替换成编辑器"); },
    },
  };
  const plugin = {
    cliOptions: () => ({ contentRoot: "C:/vault/InLoopContent" }),
    selectArticle: (value) => { selected = value; },
    refreshPreview: () => {},
  };
  const view = new viewModule.InloopPreviewView({ app }, plugin);
  const row = view.renderArticleRow({ path: "2026/002-b/index.md", dir_name: "002-b", parsable: false }, false);
  const title = row.children[0].children[0];
  check("文章标题是可键盘操作的按钮", title.tag === "button" && typeof title.onclick === "function");
  try {
    await view.openArticle({ path: "2026/002-b/index.md" });
    check("点击文章在编辑叶子打开并选择，保留面板", opened === file && selected === file);
  } catch (error) {
    check("点击文章在编辑叶子打开并选择，保留面板", false, String(error));
  }
  const sizing = new viewModule.InloopPreviewView({ app: {} }, { settings: { previewWidth: 430 } });
  sizing.previewEl = new TestElement();
  sizing.applyPreviewWidth();
  check("旧的 430px 设置不再限制侧栏预览宽度", sizing.previewEl.style.width === "100%");
  plugin.currentArticle = () => file;
  plugin.checkCurrent = async () => ({
    error_count: 1, warning_count: 1,
    article: {
      errors: [{ code: "IMG001", message: "正文图片不存在，请修正路径", line: 23 }],
      warnings: [{ code: "MD103", message: "公式降级为文本", line: null }],
    },
    manual_checks: ["请在微信手机预览中确认排版"],
  });
  view.validationEl = new TestElement();
  try {
    await view.checkArticle();
    const text = view.validationEl.allText();
    check("发布前检查区分错误、提醒和人工确认", text.includes("必须修复") && text.includes("建议处理") && text.includes("人工确认") && text.includes("正文图片不存在"));
    const findButton = (node) => node.children.find(c => c.tag === "button") ?? node.children.map(findButton).find(Boolean);
    const locate = findButton(view.validationEl);
    check("诊断带有定位按钮", typeof locate?.onclick === "function");
    if (locate) {
      await locate.onclick();
      check("定位打开中间编辑器并跳到源文件行", opened === file && openState?.eState?.line === 22 && openState?.state?.mode === "source");
    }
  } catch (error) { check("发布前检查显示结构化结果", false, String(error)); }
}
{
  const htmlPath = join(outDir, "preview.html");
  writeFileSync(htmlPath, "<body>旧文章正文</body>", "utf8");
  let slug = "001-a";
  let finish;
  const delayed = new Promise(resolve => { finish = resolve; });
  const plugin = {
    activeSlug: () => slug,
    currentArticle: () => ({ path: `${slug}/index.md` }),
    buildCurrent: () => delayed,
    runRaw: () => delayed,
    getLastBuild: () => null,
  };
  const view = new viewModule.InloopPreviewView({ app: { workspace: { getActiveFile: () => null } } }, plugin);
  view.previewEl = new TestElement();
  view.statusEl = new TestElement();
  view.readArticleText = () => null;
  const pending = view.renderPreview();
  slug = "002-b";
  finish({ html_path: htmlPath, output_dir: outDir, body_images: [], content_hash: "old" });
  await pending;
  check("切到 B 后 A 的慢请求不能写入预览", !view.previewEl.children.some(c => c.tag === "iframe"));
  plugin.buildCurrent = async () => { throw new Error("测试构建失败"); };
  plugin.runRaw = plugin.buildCurrent;
  await view.renderPreview();
  check("失败状态明确且带原因", view.statusEl.allText().includes("更新失败") && view.previewEl.allText().includes("测试构建失败"));
}
{
  const file = { path: "a/index.md" };
  let revision = 1;
  const view = new viewModule.InloopPreviewView({ app: {} }, {
    currentArticle: () => file,
    articleVersion: () => revision,
  });
  view.validationEl = new TestElement();
  view.renderCurrentArticle();
  view.validationEl.setText("文章属性校验通过。");
  revision += 1;
  view.renderCurrentArticle();
  check("同篇编辑后不保留过期校验通过提示", !view.validationEl.allText().includes("校验通过"));
}

globalThis.TestMarkdownView = class {};
const buildModule = await bundle("src/main.ts", "build-main.cjs", [...hostPlugins, {
  name: "cli-test-boundary",
  setup(builder) {
    builder.onResolve({ filter: /^\.\/inloop\/cli$/ }, () => ({ path: "cli", namespace: "test-cli" }));
    builder.onLoad({ filter: /.*/, namespace: "test-cli" }, () => ({
      contents: `export const buildArticle = (...args) => globalThis.buildStub(...args);
        export const checkArticle = (...args) => globalThis.checkStub(...args);
        export const createArticle = () => {};
        export const deleteArticle = () => {};
        export const listArticles = () => {};
        export const runCli = () => {};
        export const setStatus = () => {};
        export const guessExecutable = () => {};
        export const STATUSES = [];`,
      loader: "js",
    }));
  },
}]);
console.log("保存与构建版本绑定");
{
  const plugin = new buildModule.default();
  const file = (name) => ({ name: "index.md", extension: "md", path: `InLoopContent/2026/${name}/index.md`, parent: { name } });
  const a = file("001-a");
  const b = file("002-b");
  let active = a;
  let saved = false;
  const editor = new globalThis.TestMarkdownView();
  editor.file = a;
  editor.save = async () => { saved = true; };
  plugin.settings.contentRoot = "C:/vault/InLoopContent";
  plugin.cliOptions = () => ({});
  plugin.app = {
    vault: { adapter: { getBasePath: () => "C:/vault" } },
    workspace: {
      getActiveFile: () => active,
      getMostRecentLeaf: () => null,
      getLeavesOfType: () => [{ view: editor }],
    },
  };
  const output = { metadata: { title: "文章 A" }, body_images: [] };
  globalThis.buildStub = async (_options, target) => {
    check("构建前已保存当前编辑器且目标为 A", saved && target === "001-a");
    return output;
  };
  await plugin.buildCurrent();
  check("当前文章构建后即可打开产物", plugin.getLastBuild() === output);
  globalThis.buildStub = async () => { throw new Error("构建失败"); };
  try { await plugin.buildCurrent(); } catch { /* 本用例预期失败 */ }
  check("重建失败不能继续提供旧产物", plugin.getLastBuild() === null);
  let finish;
  let started;
  const startedPromise = new Promise(resolve => { started = resolve; });
  globalThis.buildStub = () => { started(); return new Promise(resolve => { finish = resolve; }); };
  const pending = plugin.buildCurrent();
  await startedPromise;
  active = b;
  plugin.activeSlug();
  finish(output);
  let rejected = false;
  try { await pending; } catch { rejected = true; }
  check("切换文章后旧构建被拒绝且产物不可用", rejected && plugin.getLastBuild() === null);
  active = a;
  globalThis.checkStub = async (_options, _target, publish) => {
    check("面板请求完整发布前检查", publish === true);
    return { article: { errors: [{ code: "E1", level: "ERROR", message: "错误示例", line: 8 }], warnings: [{ code: "W1", level: "WARNING", message: "警告示例" }] } };
  };
  const checked = await plugin.checkCurrent();
  check("校验界面保留单篇错误、警告和行号", checked.article.errors[0].message === "错误示例" && checked.article.errors[0].line === 8 && checked.article.warnings[0].message === "警告示例");
  let releaseFirst;
  let markStarted;
  let calls = 0;
  const producedPath = join(outDir, "serial-build.html");
  const firstStarted = new Promise(resolve => { markStarted = resolve; });
  globalThis.buildStub = async () => {
    calls += 1;
    const content = calls === 1 ? "旧内容" : "新内容";
    if (calls === 1) {
      markStarted();
      await new Promise(resolve => { releaseFirst = resolve; });
    }
    writeFileSync(producedPath, content, "utf8");
    return output;
  };
  const oldBuild = plugin.buildCurrent().catch(error => error);
  await firstStarted;
  plugin.invalidateArticle();
  const newBuild = plugin.buildCurrent();
  // 等待第二次请求越过保存的微任务，但不释放第一个构建。
  await new Promise(resolve => setImmediate(resolve));
  check("预览与复制共享队列，旧构建结束前不启动新构建", calls === 1);
  releaseFirst();
  const oldResult = await oldBuild;
  await newBuild;
  check("旧构建被拒绝，新构建随后成功且成为唯一产物", oldResult instanceof Error && calls === 2 && plugin.getLastBuild() === output);
  check("最后落盘的内容属于新版本", readFileSync(producedPath, "utf8") === "新内容");
  let releaseSuccess;
  let signalStarted;
  const successStarted = new Promise(resolve => { signalStarted = resolve; });
  calls = 0;
  globalThis.buildStub = async () => {
    calls += 1;
    if (calls === 1) {
      signalStarted();
      await new Promise(resolve => { releaseSuccess = resolve; });
      return output;
    }
    throw new Error("第二次构建失败");
  };
  const first = plugin.buildCurrent();
  await successStarted;
  const second = plugin.buildCurrent().catch(error => error);
  await new Promise(resolve => setImmediate(resolve));
  releaseSuccess();
  await first;
  const secondResult = await second;
  check("同版本排队重建失败不遗留前一次产物", secondResult instanceof Error && plugin.getLastBuild() === null);
}

rmSync(outDir, { recursive: true, force: true });

console.log("");
console.log(`结果：${passed} 通过 / ${failed} 失败`);
process.exit(failed === 0 ? 0 : 1);
