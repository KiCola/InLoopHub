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
 * 由产物目录构造 iframe 需要的 `base href`。
 *
 * ## 两条实测确认的硬约束（都不要"顺手优化"掉）

 * 1. **iframe 用 `srcdoc` 而不是 `src` 指向 `file://`。**
 *    曾为"图片不显示"把它改成 `src="file:///..."`，结果**整块预览变白**：
 *    sandbox 的源隔离会拒绝 `file://` 导航，连文字都没了。
 *    `srcdoc` 把内容内联、不需要导航，因此不受这条策略影响。
 * 2. **必须有 `<base href>`。** `srcdoc` 文档没有 URL 基址，产物里的图片是
 *    相对路径，没有 base 就会相对 Obsidian 的 `app://` 基址解析而全部失败。
 *
 * Windows 盘符要额外加一个斜杠：`E:/a/b` → `file:///E:/a/b`；
 * POSIX 路径已经是 `/` 开头，只需补两个斜杠。
 *
 * @param outputDir 产物目录，Windows 或 POSIX 形式都可以
 * @returns 形如 `file:///E:/InLoopHub/dist/wechat/001-x/` 的字符串（以斜杠结尾）
 */
export function frameBaseHref(outputDir: string): string {
  const normalized = outputDir.replace(/\\/g, "/").replace(/\/+$/, "");
  if (/^[A-Za-z]:/.test(normalized)) {
    return `file:///${normalized}/`;
  }
  return `file://${normalized.startsWith("/") ? "" : "/"}${normalized}/`;
}

/** 单张图内联进预览的上限；超过就保留原路径（预览可能裂图，但不撑爆 iframe） */
export const INLINE_IMAGE_LIMIT_BYTES = 4 * 1024 * 1024;

/**
 * 把预览 HTML 里的本地图片换成 data URI。
 *
 * ## 为什么必须这么做
 *
 * 预览用 `<iframe srcdoc>` 承载产物 HTML。而 **Obsidian 的渲染进程基于
 * `app://obsidian.md`**；当 iframe 带 `sandbox="allow-same-origin"` 时，
 * Chromium 在父级不是标准源的情况下**不会**把父级源交给 iframe，
 * iframe 于是成为**不透明源（opaque origin）**。
 * 不透明源去加载 `file://` 子资源会被源策略/CSP 拦掉——
 * 表现就是：**文字与样式全对，图片一片空白，连占位高度都没有**（用户实测）。
 *
 * 我用 headless Chrome 反复验证过 `srcdoc + <base href>` 能显示图片，
 * 但那是**顶层 `file://` 页面里的 iframe**，与 Obsidian 的 `app://` 父级不同源，
 * 因此那条结论不适用于 Obsidian。data URI 不走 file://，**不受这条策略影响**。
 *
 * ## 为什么不违反"禁止内联图片"的约束
 *
 * 任务书禁止的是把图片内联进**构建产物**——那会让图片无法上传到平台换取地址、
 * 堵死后续的自动发布。这里改的只是**插件预览时临时构造的 HTML 字符串**，
 * 不落盘、不影响 `article.html` / `metadata.json`，产物里的图片仍然是独立文件
 * 且带结构化清单。
 *
 * @param body 正文 HTML 片段
 * @param outputDir 产物目录（图片相对于它）
 * @param readBinary 读二进制文件的回调，由调用方注入（便于测试）
 * @returns 替换后的 HTML 与替换张数
 */
export function inlineImages(
  body: string,
  outputDir: string,
  readBinary: (path: string) => Uint8Array | null,
): { html: string; inlined: number; skipped: number } {
  let inlined = 0;
  let skipped = 0;

  const base = outputDir.replace(/\\/g, "/").replace(/\/+$/, "");
  const html = body.replace(/<img\b[^>]*>/gi, (tag) => {
    const match = /\bsrc\s*=\s*"([^"]*)"/i.exec(tag);
    if (!match) return tag;
    const src = match[1];
    // 外链、data URI、绝对 URL 都不动
    if (!src || /^(https?:|data:|\/\/)/i.test(src)) return tag;

    // src 是 URL，磁盘路径要解码（含空格与中文时会被百分号编码）
    const decoded = decodeURIComponent(src);
    const bytes = readBinary(`${base}/${decoded}`);
    if (!bytes || bytes.length === 0 || bytes.length > INLINE_IMAGE_LIMIT_BYTES) {
      skipped += 1;
      return tag;
    }
    const encoded = base64FromBytes(bytes);
    if (!encoded) {
      skipped += 1;
      return tag;
    }
    inlined += 1;
    const dataUri = `data:${mimeForPath(decoded)};base64,${encoded}`;
    return tag.replace(match[0], `src="${dataUri}"`);
  });

  return { html, inlined, skipped };
}

/** 按扩展名给 MIME；认不出时用通用二进制类型（浏览器仍会按内容嗅探） */
export function mimeForPath(path: string): string {
  const lower = path.toLowerCase();
  if (lower.endsWith(".png")) return "image/png";
  if (lower.endsWith(".jpg") || lower.endsWith(".jpeg")) return "image/jpeg";
  if (lower.endsWith(".gif")) return "image/gif";
  if (lower.endsWith(".webp")) return "image/webp";
  if (lower.endsWith(".bmp")) return "image/bmp";
  if (lower.endsWith(".svg")) return "image/svg+xml";
  if (lower.endsWith(".avif")) return "image/avif";
  return "application/octet-stream";
}

/** 字节数组 → base64。不依赖 Buffer/btoa 的存在性，手写实现。 */
export function base64FromBytes(bytes: Uint8Array): string {
  const alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
  let out = "";
  for (let i = 0; i < bytes.length; i += 3) {
    const b0 = bytes[i] ?? 0;
    const b1 = bytes[i + 1];
    const b2 = bytes[i + 2];
    out += alphabet[b0 >> 2];
    out += alphabet[((b0 & 0x03) << 4) | ((b1 ?? 0) >> 4)];
    out += b1 === undefined ? "=" : alphabet[((b1 & 0x0f) << 2) | ((b2 ?? 0) >> 6)];
    out += b2 === undefined ? "=" : alphabet[b2 & 0x3f];
  }
  return out;
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
