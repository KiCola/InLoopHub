/**
 * 纯函数：预览与剪贴板里那些"可以脱离 Obsidian 单独推理"的逻辑。
 *
 * 为什么单独一个文件：上一轮 M3 有两个阻塞缺陷（预览图片全坏、复制丢排版）
 * 都落在这一层，而当时的测试一条都没覆盖到——因为它们埋在 `ItemView` 里，
 * 没法在 Node 里跑。抽出来之后就能被 `scripts/unit.mjs` 直接测。
 *
 * 本文件**不得** import 任何 obsidian 模块，否则就失去可测性。
 */

/**
 * iframe 的 sandbox 取值。
 *
 * **不能是空串**：空 sandbox 会阻止一切 `file://` 加载，预览里所有图片都会变成坏图。
 * `allow-same-origin` 恰好允许加载本地资源，又不授予脚本执行权限——
 * 因此既解决了图片，也保留了"隔离产物样式"这个用 sandbox 的本意。
 *
 * （独立审核用 headless Chrome 做了 6 组对照实测确认。）
 */
export const FRAME_SANDBOX = "allow-same-origin";

/**
 * 把磁盘路径转成 `file://` URL。
 *
 * 预览用 iframe 的 `src` 指向产物 HTML（而不是塞进 `srcdoc`），因此需要这个转换。
 * 为什么不用 `srcdoc`：它生成的文档**没有 URL 基址**，里面相对路径的图片要靠
 * 手动注入 `<base>`；这条路在 Chrome 里能用，在 Electron 里却不一定。
 * 让 iframe 真的导航到一个 `file://` 文档更可靠，且不必再注入 base。
 *
 * Windows 盘符要额外加一个斜杠：`E:/a/b` → `file:///E:/a/b`；
 * POSIX 路径已经是 `/` 开头，只需补两个斜杠。
 */
export function pathToFileUrl(path: string): string {
  const normalized = path.replace(/\\/g, "/");
  if (/^[A-Za-z]:/.test(normalized)) {
    return `file:///${normalized}`;
  }
  return `file://${normalized.startsWith("/") ? "" : "/"}${normalized}`;
}

/**
 * 由产物目录构造 iframe 需要的 `base href`。
 *
 * 保留它是为了兼容"把 HTML 塞进 srcdoc"的做法（预览的早期实现）；
 * 现在预览走 `src` + `pathToFileUrl`，已不需要 base。
 *
 * @param outputDir 产物目录，Windows 或 POSIX 形式都可以
 * @returns 形如 `file:///E:/InLoopHub/dist/wechat/001-x/` 的字符串（以斜杠结尾）
 */
export function frameBaseHref(outputDir: string): string {
  return `${pathToFileUrl(outputDir.replace(/\/+$/, ""))}/`;
}

/**
 * 把正文包进最小 HTML 文档供 iframe 显示。
 *
 * 不引外部样式，只给 body 一点留白——产物的样式本来就是全内联的。
 */
export function wrapForFrame(body: string, baseHref: string): string {
  return [
    "<!DOCTYPE html>",
    '<html><head><meta charset="utf-8">',
    `<base href="${baseHref}">`,
    "<style>",
    "html,body{margin:0;padding:0;}",
    "body{padding:12px;background:#fff;}",
    "</style></head><body>",
    body,
    "</body></html>",
  ].join("");
}

/**
 * 从完整 HTML 文档里取出 `<body>` 内容。
 *
 * 微信只接受正文片段；把 `<!DOCTYPE html>` 与 `<head>` 一起粘进去会带进多余文本。
 * 没有 body 标签时退回原文（产物本身可能已是片段）。
 */
export function extractBodyHtml(html: string): string {
  const match = /<body[^>]*>([\s\S]*?)<\/body>/i.exec(html);
  return match ? (match[1] ?? "").trim() : html.trim();
}

/**
 * 粗略去掉标签，得到可读纯文本。
 *
 * 用于剪贴板的**纯文本 flavor**（粘到不支持 HTML 的地方时用），
 * 因此不需要精确——保留块级元素处的换行即可。
 */
export function stripHtml(html: string): string {
  return html
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/(p|div|h[1-6]|li|tr|blockquote|pre)>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}
