/**
 * InLoop 手记 Obsidian 插件。
 *
 * 职责：**只做界面**。渲染交给 Python 工具 inloop（见 inloop/cli.ts）。
 *
 * 三块功能：
 * 1. 文章面板：列出内容目录里的文章，新建 / 打开 / 删除
 * 2. 实时预览：编辑时右侧实时显示微信公众号排版效果
 * 3. 构建并复制：一键把正文 HTML 放进剪贴板，去公众号后台粘贴
 */

import { MarkdownView, Notice, Plugin, TFile, debounce } from "obsidian";
import {
  buildArticle,
  checkArticle,
  createArticle,
  deleteArticle,
  listArticles,
  runCli,
  setStatus,
  type BuildResult,
  type CliOptions,
} from "./inloop/cli";
import {
  DEFAULT_SETTINGS,
  InloopSettingTab,
  detectRepoRoot,
  invalidateRepoRootCache,
  resolveContentRoot,
  resolveExecutable,
  warmRepoRootCache,
  writePointerFile,
  type InloopSettings,
} from "./settings";
import { VIEW_TYPE_INLOOP_PREVIEW, InloopPreviewView } from "./view";
import { installStyles } from "./styles";
import { openWithSystem, copyRichText, readTextFile, vaultBasePath } from "./obsidian-env";

export default class InloopPlugin extends Plugin {
  settings: InloopSettings = { ...DEFAULT_SETTINGS };

  /** 最近一次构建结果，供"复制到公众号"使用 */
  private lastBuild: BuildResult | null = null;
  private lastBuildPath = "";
  private selectedArticle: TFile | null = null;
  private articleRevision = 0;
  private buildQueue: Promise<unknown> = Promise.resolve();

  /** 是否正在开面板（用于阻断 active-leaf-change 造成的递归开面板） */
  private openingPanel = false;

  /** 防抖后的预览刷新：打字时不至于每个字符都触发一次 Python 调用 */
  private refreshSoon: (() => void) | null = null;

  async onload(): Promise<void> {
    await this.loadSettings();
    // 预读 vault 里的工具指向文件（跨盘场景下这是唯一可行的自动发现方式）。
    // 读一次缓存起来，之后同步取用——渲染路径不能被异步读拖慢。
    await warmRepoRootCache(this.app);
    installStyles();

    this.registerView(VIEW_TYPE_INLOOP_PREVIEW, (leaf) => new InloopPreviewView(leaf, this));

    this.addRibbonIcon("newspaper", "InLoop 手记", () => {
      void this.activatePreview();
    });

    this.addCommand({
      id: "open-panel",
      name: "打开面板（右侧栏）",
      callback: () => void this.activatePreview(),
    });

    this.addCommand({
      id: "open-panel-sidebar",
      name: "打开右侧栏预览",
      callback: () => void this.activatePreview(),
    });

    this.addCommand({
      id: "diagnose-paths",
      name: "诊断：路径与预览判定",
      callback: () => this.diagnosePaths(),
    });

    this.addCommand({
      id: "new-article",
      name: "新建推文",
      callback: () => this.promptNewArticle(),
    });

    this.addCommand({
      id: "copy-for-wechat",
      name: "构建并复制到公众号",
      callback: () => void this.buildAndCopy(),
    });

    this.addCommand({
      id: "refresh-preview",
      name: "刷新预览",
      callback: () => this.refreshPreview(),
    });

    // 实时预览：监听当前文件的编辑与切换。
    // 用 debounce 包一层——渲染一次要调用 Python，成本不低。
    this.refreshSoon = debounce(
      () => this.refreshPreview(),
      this.settings.previewDebounceMs,
      true,
    ) as unknown as () => void;

    this.registerEvent(
      this.app.workspace.on("editor-change", (_editor, info) => {
        // 用回调给的 info.file 而不是 workspace.getActiveFile()：
        // 多面板时"活动文件"未必是正在编辑的那个，info.file 才是权威来源。
        // （独立审核核对了 MarkdownFileInfo 接口：get file(): TFile | null）
        if (this.isActiveArticle(info.file)) {
          this.selectArticle(info.file);
          this.invalidateArticle();
          this.refreshSoon?.();
        }
      }),
    );

    this.registerEvent(this.app.workspace.on("file-open", (file) => {
      this.selectArticle(file);
      this.refreshPreview();
    }));
    this.registerEvent(this.app.vault.on("modify", (file) => {
      if (file === this.selectedArticle) {
        this.invalidateArticle();
        this.refreshSoon?.();
      }
    }));
    this.registerEvent(this.app.vault.on("rename", () => {
      this.invalidateArticle();
      this.refreshPreview();
    }));
    this.registerEvent(this.app.vault.on("delete", (file) => {
      if (file === this.selectedArticle || this.selectedArticle?.path.startsWith(file.path + "/")) {
        this.selectedArticle = null;
        this.invalidateArticle();
        this.refreshPreview();
      }
    }));

    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => {
        // 正在开面板时直接返回：`activatePreview` 内部的 setViewState 会再次触发
        // 本事件，而那一刻新叶子还没被注册成预览类型——
        // 不拦住就会递归开出一串面板。这个坑很隐蔽，必须用标记挡住。
        if (this.openingPanel) return;

        // 打开一篇文章时：如果面板还没开，自动在右侧栏打开。
        // 否则用户会看到"打开文章但右侧什么都没有"，以为预览坏了——
        // 而其实只是面板没打开。这是实测反馈过的困惑点。
        const slug = this.activeSlug();
        if (slug && this.app.workspace.getLeavesOfType(VIEW_TYPE_INLOOP_PREVIEW).length === 0) {
          void this.activatePreview();
          return;
        }
        this.refreshPreview();
      }),
    );

    this.addSettingTab(new InloopSettingTab(this.app, this));
  }

  onunload(): void {
    // Obsidian 会在插件卸载时自动清理 registerView / registerEvent 注册的东西
  }

  async loadSettings(): Promise<void> {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    if (this.refreshSoon) {
      this.refreshSoon = debounce(
        () => this.refreshPreview(),
        this.settings.previewDebounceMs,
        true,
      ) as unknown as () => void;
    }
  }

  async saveSettings(): Promise<void> {
    await this.saveData(this.settings);
  }

  /**
   * 把当前生效的工具仓库路径写进 vault 的指向文件。
   *
   * 好处是它随坚果云同步：换电脑或重装插件都不必重填。
   * 跨盘场景（本机：vault 在 C、工具在 E）无法靠搜索发现，只能由人告诉一次，
   * 因此这个文件就是那次告知的持久化形式。
   */
  async rememberRepoRoot(repoRoot: string): Promise<void> {
    await writePointerFile(this.app, repoRoot);
    invalidateRepoRootCache();
    await warmRepoRootCache(this.app);
  }

  /** 更新设置后清掉探测缓存，让新值立刻生效 */
  refreshDetectionCache(): void {
    invalidateRepoRootCache();
    void warmRepoRootCache(this.app);
  }

  // --- 路径与调用参数 -----------------------------------------------------

  /** 组装调用 Python 所需的一切；路径探测集中在 settings.ts */
  cliOptions(): CliOptions {
    const repoRoot = detectRepoRoot(this.app, this.settings);
    return {
      executable: resolveExecutable(this.app, this.settings),
      contentRoot: resolveContentRoot(this.app, this.settings),
      ...(repoRoot ? { repoRoot } : {}),
    };
  }

  /**
   * 判断某个文件是不是"内容目录里的文章正文"。
   *
   * 只认 `<内容目录>/<年份>/<文章>/index.md`，这样在别处编辑笔记时
   * 不会触发无意义的渲染。
   */
  isActiveArticle(file: TFile | null): boolean {
    if (!file) return false;
    // 与 Python 在 Windows 上的文件查找一致，重命名为 Index.md 后仍是正文。
    const name = process.platform === "win32" ? file.name.toLowerCase() : file.name;
    if (name !== "index.md") return false;
    return this.isArticleLocation(file);
  }

  private isArticleLocation(file: TFile): boolean {
    const contentRoot = resolveContentRoot(this.app, this.settings).replace(/\\/g, "/").replace(/\/+$/, "");
    const base = vaultBasePath(this.app);
    if (!base) return false;
    const relative = `${base}/${file.path.replace(/\\/g, "/")}`;
    return relative.startsWith(contentRoot + "/") &&
      relative.slice(contentRoot.length + 1).split("/").length === 3;
  }

  /** 明确记录选择；面板取得焦点或打开普通笔记时保留当前文章。 */
  selectArticle(file: TFile | null): void {
    if (!file || file.extension.toLowerCase() !== "md" || !this.isArticleLocation(file)) return;
    if (this.selectedArticle !== file) {
      this.selectedArticle = file;
      this.invalidateArticle();
    }
  }

  private invalidateArticle(): void {
    this.articleRevision += 1;
    this.lastBuild = null;
  }

  currentArticle(): TFile | null {
    this.selectArticle(this.app.workspace.getActiveFile());
    if (!this.selectedArticle) {
      const view = this.app.workspace.getMostRecentLeaf()?.view as { file?: TFile } | undefined;
      this.selectArticle(view?.file ?? null);
    }
    return this.isActiveArticle(this.selectedArticle) ? this.selectedArticle : null;
  }

  articleHint(): string {
    this.currentArticle();
    if (this.selectedArticle && !this.isActiveArticle(this.selectedArticle)) {
      return `正文入口无法识别：${this.selectedArticle.path}。请将正文恢复为文章目录内的 index.md；修改文章标题请编辑 title 属性。`;
    }
    return "点击列表标题或打开文章的 index.md 开始；文章标题在 title 属性中修改。";
  }

  /** 当前选择的文章目录名；不猜测其他已打开文章。 */
  activeSlug(): string {
    return this.currentArticle()?.parent?.name ?? "";
  }

  /** 仅供诊断列出编辑器文件；操作目标由 selectedArticle 决定。 */
  private *candidateArticleFiles(): Generator<TFile> {
    const seen = new Set<string>();
    const emit = function* (file: TFile | null | undefined): Generator<TFile> {
      if (file && !seen.has(file.path)) {
        seen.add(file.path);
        yield file;
      }
    };

    yield* emit(this.app.workspace.getActiveFile());

    // 最近使用过的叶子（例如用户刚在笔记里写完，又点了预览面板）
    const recent = this.app.workspace.getMostRecentLeaf();
    const recentView = recent?.view as { file?: TFile | null } | undefined;
    yield* emit(recentView?.file ?? null);

    // 列出其他打开的正文用于排障，不将其作为操作目标的回退。
    for (const leaf of this.app.workspace.getLeavesOfType("markdown")) {
      const view = leaf.view as { file?: TFile | null };
      yield* emit(view.file ?? null);
    }
  }

  // --- 预览 ---------------------------------------------------------------

  /**
   * 诊断：把"预览判定"用到的每个路径都打出来。
   *
   * 为什么需要它：`isActiveArticle` 返回 false 会让预览、构建、复制全部失效，
   * 但它不报错、只是安静地判定"这不是文章"。而失败的可能是配置、vault 路径、
   * 大小写、分隔符中的任何一个，**靠读代码猜不出来**。
   * 这个命令把实际值摆出来，一次就能定位。
   */
  diagnosePaths(): void {
    const file = this.app.workspace.getActiveFile();
    const base = vaultBasePath(this.app);
    const contentRoot = resolveContentRoot(this.app, this.settings).replace(/\\/g, "/");
    // 当前文件拼成绝对路径后的样子：用来肉眼核对"前缀判断"为什么成立或不成立
    const absolute = `${base}/${(file?.path ?? "").replace(/\\/g, "/")}`;

    const lines = [
      "【当前文件】",
      `  名称：${file?.name ?? "（没有打开文件）"}`,
      `  扩展名：${file?.extension ?? "-"}`,
      `  vault 内路径：${file?.path ?? "-"}`,
      `  拼成绝对路径：${absolute}`,
      `  以内容目录开头：${absolute.startsWith(contentRoot + "/")}`,
      "",
      "【vault 根】",
      `  ${base || "（取不到）"}`,
      "",
      "【设置里的内容目录】",
      `  ${resolveContentRoot(this.app, this.settings) || "（空）"}`,
      `  规范化后：${contentRoot}`,
      "",
      "【候选文件（按可信度）】",
      ...[...this.candidateArticleFiles()].map(
        (candidate, index) =>
          `  ${index + 1}. ${candidate.path}  → ${
            this.isActiveArticle(candidate) ? "是文章" : "不是文章"
          }`,
      ),
      "",
      "【结论】",
      `  isActiveArticle(当前文件) = ${this.isActiveArticle(file)}`,
      `  activeSlug = ${this.activeSlug() || "（空，预览不会渲染）"}`,
    ];

    // 用 Notice 放不下这么多行，同时打印到控制台并弹窗给关键几行
    for (const line of lines) console.log(`[InLoop 诊断] ${line}`);
    new Notice(lines.join("\n"), 30000);
  }

  /** 在右侧栏打开文章列表与预览，中间工作区保留给编辑器。 */
  async activatePreview(): Promise<void> {
    // 阻断 active-leaf-change 递归：setViewState 会再次触发那个事件，
    // 而那一刻新叶子还没被注册成预览类型，不拦住就会开出一串面板。
    if (this.openingPanel) return;
    this.openingPanel = true;
    try {
      await this.openPanel();
    } finally {
      this.openingPanel = false;
    }
  }

  private async openPanel(): Promise<void> {
    const workspace = this.app.workspace;
    const existing = workspace.getLeavesOfType(VIEW_TYPE_INLOOP_PREVIEW);
    const leaf = existing.find(item => item.getRoot() === workspace.rightSplit)
      ?? workspace.getRightLeaf(false);

    if (!leaf) {
      new Notice(
        "没能创建预览面板。可以手动打开：命令面板 → 「InLoop 手记：打开面板」。",
        10000,
      );
      return;
    }

    await leaf.setViewState({ type: VIEW_TYPE_INLOOP_PREVIEW, active: true });
    // 新侧栏就绪后才关闭旧的 InLoop 面板，不影响其他插件标签。
    for (const duplicate of existing) {
      if (duplicate !== leaf) duplicate.detach();
    }
    await workspace.revealLeaf(leaf);
    this.refreshPreview();
  }

  /** 让预览视图重新渲染当前文章 */
  refreshPreview(): void {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_INLOOP_PREVIEW)) {
      const view = leaf.view;
      if (view instanceof InloopPreviewView) {
        void view.render();
      }
    }
  }

  // --- 新建 ---------------------------------------------------------------

  promptNewArticle(): void {
    for (const leaf of this.app.workspace.getLeavesOfType(VIEW_TYPE_INLOOP_PREVIEW)) {
      const view = leaf.view;
      if (view instanceof InloopPreviewView) {
        view.showNewArticleForm();
      }
    }
    void this.activatePreview();
  }

  /**
   * 供视图调用：真正执行新建。
   *
   * 返回 `content_root` 与相对路径——视图要先把绝对路径转成 **vault 内路径**
   * 才能用 `vault.getAbstractFileByPath()` 打开文件。
   *
   * **不再多跑一次 `list` 去猜哪篇是新的**：那既慢（多一次 Python 启动，约 300ms）
   * 又可能认错（并发或同名 slug 时）。这条路径原先就是坏的：`new` 当时没有
   * JSON 输出，解析失败会让插件把"创建成功"报成"创建失败"。
   */
  async createArticleFromForm(input: {
    title: string;
    slug: string;
    category: string;
    template: string;
    tags: string;
    summary: string;
  }): Promise<{ contentRoot: string; path: string }> {
    const created = await createArticle(this.cliOptions(), input);
    if (!created.path) {
      throw new Error(
        "创建成功但没有拿到文章路径（inloop 的输出缺少 path 字段）。" +
          "这通常说明插件与 inloop 版本不匹配，请更新到同一版本。",
      );
    }
    return { contentRoot: created.content_root ?? "", path: created.path };
  }

  // --- 构建并复制 ---------------------------------------------------------

  /**
   * 构建当前文章并把正文 HTML 放进剪贴板。
   *
   * 为什么复制的是**渲染后的 HTML 而不是 Markdown**：微信编辑器不解析 Markdown，
   * 只认粘贴进来的 HTML。这也是整个工具存在的意义。
   */
  async buildAndCopy(): Promise<void> {
    const slug = this.activeSlug();
    if (!slug) {
      new Notice(this.articleHint());
      return;
    }

    const notice = new Notice("正在构建…", 0);
    try {
      const result = await this.buildCurrent();

      const html = readTextFile(result.html_path);
      const body = extractBody(html);
      // 必须同时写入 HTML flavor：微信编辑器靠 text/html 取得内联样式，
      // 只用 writeText（纯文本）粘过去会丢掉全部排版。
      const outcome = await copyRichText(body);
      notice.hide();

      const imageHint =
        result.body_images.length > 0
          ? `另有 ${result.body_images.length} 张正文图片需在编辑器里手动上传（见面板里的清单）`
          : "本文没有正文图片";

      if (outcome.wroteHtml) {
        new Notice(`✓ 已复制《${String(result.metadata.title ?? slug)}》正文到剪贴板\n${imageHint}`, 8000);
      } else {
        // 静默降级最糟：用户会以为"工具就这样"，而实际是排版丢了
        new Notice(
          "⚠️ 只写入了纯文本，粘到公众号会**丢失排版**。\n" +
            "这通常说明当前环境拿不到 Electron 的原生剪贴板。" +
            `\n${imageHint}`,
          15000,
        );
      }
    } catch (error) {
      notice.hide();
      const message = error instanceof Error ? error.message : String(error);
      new Notice(`构建失败：${message}`, 10000);
    }
  }

  /** 构建结果（面板用来显示图片清单与"打开产物"按钮） */
  getLastBuild(): BuildResult | null {
    const file = this.currentArticle();
    return file && file.path === this.lastBuildPath ? this.lastBuild : null;
  }

  articleVersion(): number {
    this.currentArticle();
    return this.articleRevision;
  }

  /** 所有插件构建共享队列，避免旧 Python 进程后写入同一个产物目录。 */
  private queueBuild<T>(operation: () => Promise<T>): Promise<T> {
    const pending = this.buildQueue.then(operation);
    // 调用方仍收到原始错误；队列尾部恢复，让下一次构建有机会执行。
    this.buildQueue = pending.catch(() => undefined);
    return pending;
  }

  /** 等待编辑器保存，然后绑定目标和版本；旧请求不得成为当前产物。 */
  private async saveArticle(file: TFile): Promise<void> {
    for (const leaf of this.app.workspace.getLeavesOfType("markdown")) {
      if (leaf.view instanceof MarkdownView && leaf.view.file === file) {
        await leaf.view.save();
        break;
      }
    }
    if (this.currentArticle() !== file) throw new Error("当前文章已切换，请重试。");
  }

  async buildCurrent(): Promise<BuildResult> {
    const file = this.currentArticle();
    if (!file) throw new Error(this.articleHint());
    this.lastBuild = null;
    await this.saveArticle(file);
    const revision = this.articleRevision;
    const assertCurrent = (): void => {
      if (this.currentArticle() !== file || revision !== this.articleRevision) {
        throw new Error("文章已切换或内容已修改，本次旧构建结果已忽略，请等待预览更新后重试。");
      }
    };
    return this.queueBuild(async () => {
      assertCurrent();
      this.lastBuild = null;
      const result = await buildArticle(this.cliOptions(), file.parent!.name);
      assertCurrent();
      this.lastBuild = result;
      this.lastBuildPath = file.path;
      return result;
    });
  }

  /** 用系统默认程序打开一个路径（通常是产物的 HTML） */
  async openPath(path: string): Promise<void> {
    // 交给系统默认程序打开：去公众号粘贴是一段浏览器里的操作，
    // 在 Obsidian 内嵌预览反而不方便。
    await openWithSystem(path);
  }

  // --- 供视图使用的小工具 -------------------------------------------------

  /** 校验当前文章，返回可读的问题描述（面板显示用） */
  async checkCurrent(): Promise<string[]> {
    const file = this.currentArticle();
    if (!file) throw new Error(this.articleHint());
    await this.saveArticle(file);
    const revision = this.articleRevision;
    const result = await checkArticle(this.cliOptions(), file.parent!.name);
    if (this.currentArticle() !== file || revision !== this.articleRevision) {
      throw new Error("文章已切换或修改，请重新校验当前文章。");
    }
    const article = result.article;
    return [...article.errors, ...article.warnings].map(
      (issue) => `${issue.code} [${issue.level}] ${issue.message}`,
    );
  }

  /** 列出文章；失败时把可读错误抛给界面 */
  async listArticlesSafe() {
    return listArticles(this.cliOptions());
  }

  /** 删除文章（界面会先确认） */
  async deleteArticleSafe(slug: string) {
    return deleteArticle(this.cliOptions(), slug);
  }

  /**
   * 切换文章状态。
   *
   * 这是 Python 侧**唯一**允许改写文章文件的场景，且只改 status 一行——
   * 因此从插件调用它没有"会不会改坏正文"的顾虑。
   */
  async setStatusSafe(slug: string, status: string) {
    return setStatus(this.cliOptions(), slug, status);
  }

  /** 直接调用任意 inloop 子命令（面板的"在工具仓库里查看"等场景） */
  async runRaw(args: string[]) {
    if (args[0] === "build-wechat") {
      return this.queueBuild(() => runCli(this.cliOptions(), args));
    }
    return runCli(this.cliOptions(), args);
  }
}

/**
 * 从完整 HTML 文档里取出 `<body>` 内容。
 *
 * 微信只接受正文片段；把 `<html><head>` 一起粘进去会带进 `<!DOCTYPE` 等文本。
 */
export function extractBody(html: string): string {
  const match = /<body[^>]*>([\s\S]*?)<\/body>/i.exec(html);
  return match ? (match[1] ?? "").trim() : html.trim();
}
