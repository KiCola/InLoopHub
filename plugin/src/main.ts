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

import { Notice, Plugin, TFile, WorkspaceLeaf, debounce } from "obsidian";
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
      name: "打开 InLoop 面板",
      callback: () => void this.activatePreview(),
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
          this.refreshSoon?.();
        }
      }),
    );

    this.registerEvent(
      this.app.workspace.on("active-leaf-change", () => {
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
    if (!file || file.extension !== "md" || file.name !== "index.md") return false;
    const contentRoot = resolveContentRoot(this.app, this.settings).replace(/\\/g, "/");
    const base = vaultBasePath(this.app);
    if (!base) return false;
    const relative = `${base}/${file.path.replace(/\\/g, "/")}`;
    return relative.startsWith(contentRoot + "/");
  }

  /** 当前打开的文章 slug（目录名），不是文章时返回空串 */
  activeSlug(): string {
    const file = this.app.workspace.getActiveFile();
    if (!this.isActiveArticle(file) || !file) return "";
    return file.parent?.name ?? "";
  }

  // --- 预览 ---------------------------------------------------------------

  async activatePreview(): Promise<void> {
    // **面板要开在右侧边栏**，不能占主编辑区。
    // 用 getLeaf(false) 会在主区新开标签页，把用户的笔记挤走——
    // 而用户要的是"左边编辑、右边看预览"。
    const existing = this.app.workspace.getLeavesOfType(VIEW_TYPE_INLOOP_PREVIEW);
    let leaf: WorkspaceLeaf | null = existing[0] ?? null;

    if (!leaf) {
      // ensureSideLeaf 是 1.7.2+ 的官方 API，语义明确（getRightLeaf 已废弃）
      leaf = await this.app.workspace.ensureSideLeaf(VIEW_TYPE_INLOOP_PREVIEW, "right", {
        active: true,
        reveal: true,
      });
    }

    if (!leaf) {
      new Notice(
        "没能在右侧边栏创建面板。可以手动打开：命令面板 → 「InLoop 手记：打开面板」。",
        10000,
      );
      return;
    }

    await leaf.setViewState({ type: VIEW_TYPE_INLOOP_PREVIEW, active: true });
    this.app.workspace.revealLeaf(leaf);
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
      new Notice("当前文件不是 InLoop 文章（需要是内容目录里的 index.md）");
      return;
    }

    const notice = new Notice("正在构建…", 0);
    try {
      const result = await buildArticle(this.cliOptions(), slug);
      this.lastBuild = result;

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
        new Notice(`✓ 已复制正文到剪贴板\n${imageHint}`, 8000);
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
    return this.lastBuild;
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
    const slug = this.activeSlug();
    if (!slug) return [];
    const result = await checkArticle(this.cliOptions(), slug);
    const article = result.articles?.[0];
    if (!article) return [];
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
