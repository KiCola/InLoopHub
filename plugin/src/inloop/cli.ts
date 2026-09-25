/**
 * 与 Python 内核的接口：调用 `inloop` 并解析其 JSON 输出。
 *
 * **渲染逻辑仍然全在 Python 里。** 这个插件只做界面——
 * 这样做的代价是用户机器上要有 Python 与 inloop，收益是不必维护第二套渲染器
 * （CSS 内联、语法着色、图片处理、校验规则都已实现并有测试覆盖）。
 *
 * 调用约定（任务书 §7.5）：
 * - 成功时 stdout 是合法 JSON，退出码 0
 * - 失败时 stdout 仍是合法 JSON（`{ok:false, error:{...}}`），退出码非 0
 * - 人类可读的提示走 stderr
 *
 * 因此这里**只解析 stdout**，stderr 仅用于在出错时提供更多上下文。
 */

import { execFile } from "node:child_process";
import { existsSync } from "node:fs";
import { promisify } from "node:util";

const execFileAsync = promisify(execFile);

/** 构建可能需要几十秒（解码图片、内联样式），给足超时 */
const TIMEOUT_MS = 120_000;
/** 只要列表时应当很快，超时更短可以让"配置错了"更快暴露 */
const QUICK_TIMEOUT_MS = 20_000;

export interface CliErrorShape {
  code: string;
  message: string;
  hint?: string;
}

/** 调用失败时抛出的错误，携带结构化信息供界面展示 */
export class InloopError extends Error {
  readonly code: string;
  readonly hint: string;

  constructor(code: string, message: string, hint = "") {
    super(message);
    this.name = "InloopError";
    this.code = code;
    this.hint = hint;
  }

  /** 面向用户的多行说明：说清「哪里错了 + 怎么改」 */
  toDisplay(): string {
    return this.hint ? `${this.message}\n\n${this.hint}` : this.message;
  }
}

export interface CliOptions {
  /** inloop 可执行文件路径 */
  executable: string;
  /** 内容目录；为空则交给 Python 侧按环境变量/配置文件解析 */
  contentRoot?: string;
  /** 工具仓库根（含 config/ 的目录） */
  repoRoot?: string;
  /** 附加环境变量 */
  env?: Record<string, string>;
}

/** inloop JSON 输出的公共字段 */
interface Envelope {
  ok: boolean;
  schema: number;
  error?: CliErrorShape;
}

export interface ArticleSummary {
  id: number;
  dir_name: string;
  slug: string;
  title: string;
  date: string;
  category: string;
  category_label: string;
  status: string;
  tags: string[];
  summary: string;
  /** 相对内容目录的正文路径 */
  path: string;
  parsable: boolean;
  reason?: string;
  errors: IssueInfo[];
  warnings: IssueInfo[];
}

export interface IssueInfo {
  code: string;
  level: string;
  message: string;
  field: string | null;
  line: number | null;
  file: string;
}

export interface ListResult extends Envelope {
  content_root: string;
  count: number;
  next_id: number;
  articles: ArticleSummary[];
}

export interface CheckResult extends Envelope {
  content_root: string;
  total: number;
  error_count: number;
  warning_count: number;
  unparsable: number;
  articles: ArticleSummary[];
}

export interface ImageEntry {
  order: number;
  kind: "body" | "cover";
  output: string;
  source: string;
  byte_size: number;
  width: number;
  height: number;
  section: string;
  alt: string;
  caption: string;
}

export interface BuildResult extends Envelope {
  content_root: string;
  output_dir: string;
  files: string[];
  html_path: string;
  preview_path: string;
  metadata_path: string;
  images: ImageEntry[];
  body_images: ImageEntry[];
  warnings: string[];
  metadata: Record<string, unknown>;
}

export interface DeletePreview extends Envelope {
  removed: boolean;
  dir_name: string;
  path: string;
  file_count: number;
  image_count: number;
}

/** 虚拟环境里 `inloop` 的候选相对路径（按当前平台优先排序） */
function venvRelativePaths(): string[] {
  return process.platform === "win32"
    ? [".venv/Scripts/inloop.exe", ".venv/bin/inloop"]
    : [".venv/bin/inloop", ".venv/Scripts/inloop.exe"];
}

/**
 * 猜一个可用的 `inloop` 路径。
 *
 * 顺序：用户显式配置 > 环境变量 INLOOP_ROOT > 基准目录及其上级里的虚拟环境 >
 * PATH 上的 `inloop`。
 *
 * **为什么要搜索而不是只查 PATH**：`inloop` 是本地 `pip install -e` 装进虚拟环境的，
 * 通常**不在 PATH 上**。只查 PATH 的结果是用户看到"找不到 inloop"却发现设置里
 * 三项都空着、不知道该填什么——这是实测踩到的问题（本机 `which inloop` 为空）。
 *
 * @param configured 用户在设置里填的路径；非空则直接采用
 * @param baseDir 搜索起点，通常是 vault 路径
 */
export function guessExecutable(configured: string, baseDir: string): string {
  if (configured.trim()) return configured.trim();

  const bases: string[] = [];
  const fromEnv = (process.env.INLOOP_ROOT ?? "").trim();
  if (fromEnv) bases.push(fromEnv);

  // 工具仓库常与 vault 平级、或在 vault 内，因此从 baseDir 逐级向上找。
  // 限制深度是为了不在整块磁盘上乱扫——那既慢又容易误命中无关目录。
  if (baseDir.trim()) {
    let current = baseDir.trim().replace(/\\/g, "/").replace(/\/+$/, "");
    for (let depth = 0; depth < 4 && current; depth += 1) {
      bases.push(current);
      const slash = current.lastIndexOf("/");
      if (slash <= 2) break; // 已到 "E:/" 这一级，再往上没有意义
      current = current.slice(0, slash);
    }
  }

  for (const base of bases) {
    for (const relative of venvRelativePaths()) {
      const candidate = `${base.replace(/\\/g, "/")}/${relative}`;
      if (existsSync(candidate)) return candidate;
    }
  }

  // 交给 PATH 解析（可能失败，由调用方给出"去哪里配置"的指引）
  return "inloop";
}

/** 组装命令行参数：全局选项必须放在子命令**之前** */
function buildArgs(contentRoot: string | undefined, args: string[]): string[] {
  const result: string[] = ["--json"];
  if (contentRoot && contentRoot.trim()) {
    result.push("--content", contentRoot.trim());
  }
  return [...result, ...args];
}

/**
 * 执行一次 inloop 调用并返回解析后的 JSON。
 *
 * @throws InloopError 找不到可执行文件、输出不是 JSON、或命令报错
 */
export async function runCli<T extends Envelope>(
  options: CliOptions,
  args: string[],
  quick = false,
): Promise<T> {
  const env = { ...process.env, ...(options.env ?? {}) };
  if (options.repoRoot) {
    // 让 Python 侧不必靠 cwd 去猜仓库根
    env.INLOOP_ROOT = options.repoRoot;
  }

  // **必须显式指定 UTF-8。**
  // 中文 Windows 上 Python 的默认标准输出编码是 GBK（本机 locale 是
  // Chinese (Simplified)_China.936）。文章路径里只要出现中文
  // （例如坚果云的「我的坚果云」），Python 写出的字节就不是 UTF-8，
  // 而 Node 按 UTF-8 解码 → 报错信息变成乱码，无法定位。
  //
  // 同时设 PYTHONUTF8 覆盖文件系统与命令行参数的编码，
  // 避免中文路径在传参环节被按 GBK 处理。
  env.PYTHONIOENCODING = "utf-8";
  env.PYTHONUTF8 = "1";

  let stdout: string;
  let stderr: string;
  try {
    const result = await execFileAsync(
      options.executable,
      buildArgs(options.contentRoot, args),
      {
        timeout: quick ? QUICK_TIMEOUT_MS : TIMEOUT_MS,
        maxBuffer: 32 * 1024 * 1024,
        windowsHide: true,
        // 显式指定解码方式，不依赖平台默认值
        encoding: "utf8",
        env,
      },
    );
    stdout = result.stdout;
    stderr = result.stderr;
  } catch (error) {
    // 命令以非 0 退出，或进程启动失败。两种都要区分：
    // - 启动了但报错：stdout 里应当有一份 JSON 错误信封
    // - 没启动（ENOENT 等）：只能靠 error.code 判断
    const failure = error as NodeJS.ErrnoException & { stdout?: string; stderr?: string };
    if (failure.code === "ENOENT") {
      throw new InloopError(
        "cli_not_found",
        `找不到 inloop 可执行文件：${options.executable}`,
        "在插件设置里填入「工具仓库根目录」（例如 E:/InLoopHub），" +
          "插件会在它的 .venv 里找到 inloop。\n" +
          "填好后点「记住到 vault」，路径会存进 vault 的 inloop-path.txt，" +
          "随同步盘走，换电脑不必重填。\n" +
          "若尚未安装 Python 环境，请先按工具仓库 README 完成安装。",
      );
    }
    stdout = failure.stdout ?? "";
    stderr = failure.stderr ?? "";
    const parsed = tryParse<T>(stdout);
    if (parsed?.error) {
      throw new InloopError(parsed.error.code, parsed.error.message, parsed.error.hint ?? "");
    }
    throw new InloopError(
      "cli_failed",
      stderr.trim() || stdout.trim() || `inloop 执行失败（${failure.code ?? "未知原因"}）`,
      "在工具仓库里手动运行同一条命令可以看到完整报错。",
    );
  }

  const parsed = tryParse<T>(stdout);
  if (!parsed) {
    throw new InloopError(
      "cli_bad_output",
      `inloop 的输出不是合法 JSON：${stdout.slice(0, 400)}`,
      "这通常说明 inloop 版本与插件不匹配。请更新到同一版本后重试。",
    );
  }
  if (parsed.error && !parsed.ok) {
    throw new InloopError(parsed.error.code, parsed.error.message, parsed.error.hint ?? "");
  }
  return parsed;
}

function tryParse<T>(text: string): T | null {
  const trimmed = text.trim();
  if (!trimmed) return null;
  try {
    return JSON.parse(trimmed) as T;
  } catch {
    return null;
  }
}

// --- 具体命令 -------------------------------------------------------------

export function listArticles(options: CliOptions): Promise<ListResult> {
  return runCli<ListResult>(options, ["list"], true);
}

export function checkArticle(options: CliOptions, slug: string): Promise<CheckResult> {
  return runCli<CheckResult>(options, ["check", slug], true);
}

export function checkAll(options: CliOptions): Promise<CheckResult> {
  return runCli<CheckResult>(options, ["check", "--all"]);
}

export function buildArticle(options: CliOptions, slug: string): Promise<BuildResult> {
  return runCli<BuildResult>(options, ["build-wechat", slug]);
}

export function deleteArticle(
  options: CliOptions,
  slug: string,
): Promise<DeletePreview | Envelope> {
  return runCli<DeletePreview | Envelope>(options, ["delete", slug, "--yes"]);
}

/** 文章状态，取值与 Python 侧一致（任务书 §4） */
export const STATUSES = [
  "idea",
  "researching",
  "draft",
  "review",
  "ready",
  "published",
] as const;
export type ArticleStatus = (typeof STATUSES)[number];

/**
 * 修改文章状态。
 *
 * 这是 Python 侧**唯一**允许改写已存在文章文件的场景，且只改 status 一行。
 * 因此从插件调用它是安全的——不会因为手滑把正文改掉。
 */
export function setStatus(
  options: CliOptions,
  slug: string,
  status: string,
): Promise<StatusResult> {
  return runCli<StatusResult>(options, ["status", slug, status], true);
}

/** `status` 命令的结果 */
export interface StatusResult extends Envelope {
  dir_name: string;
  slug: string;
  title: string;
  status: string;
  /** 改之前的状态，便于界面提示"从 X 到 Y"或回滚 */
  previous_status: string;
  path: string;
}

/** `new` 命令的结果 */
export interface NewArticleResult extends Envelope {
  /** 内容目录的绝对路径（POSIX 风格），用来把相对 path 拼成可打开的位置 */
  content_root: string;
  dir_name: string;
  slug: string;
  title: string;
  id: number;
  status: string;
  /** 相对内容目录的正文路径 */
  path: string;
  cover: string;
}

/** 新建文章的输入 */
export interface NewArticleInput {
  title: string;
  slug: string;
  category: string;
  template: string;
  tags: string;
  summary: string;
}

/**
 * 新建文章，返回**新文章的信息**（含路径）。
 *
 * 为什么必须拿到返回值：插件建完要立刻打开那篇文章。
 * 早先 `new` 没有 JSON 输出，插件只能"建完再 list 一次、按 slug 猜哪篇是新的"——
 * 多跑一次 Python 进程，而且并发时可能认错文章。
 */
export function createArticle(
  options: CliOptions,
  input: NewArticleInput,
): Promise<NewArticleResult> {
  // 注意 --yes：插件已经用表单收集过必填项，不需要 Python 侧再交互提问
  return runCli<NewArticleResult>(
    options,
    [
      "new",
      "--title",
      input.title,
      "--slug",
      input.slug,
      "--category",
      input.category,
      "--template",
      input.template,
      "--tags",
      input.tags,
      "--summary",
      input.summary,
      "--yes",
    ],
    false,
  );
}
