/**
 * 文章面板与实时预览视图。
 *
 * 布局：上方是工具栏与文章列表，下方是手机宽度的预览区。
 * 编辑文章时预览区会随输入实时更新（防抖在 main.ts 里）。
 */

import { ItemView, Notice, WorkspaceLeaf, setIcon } from "obsidian";
import type InloopPlugin from "./main";
import type { ArticleSummary, BuildResult, ImageEntry } from "./inloop/cli";
import { STATUSES } from "./inloop/cli";
import { toVaultPath } from "./obsidian-env";
import {
  FRAME_SANDBOX,
  extractBodyHtml,
  frameBaseHref,
  wrapForFrame,
} from "./preview-utils";

export const VIEW_TYPE_INLOOP_PREVIEW = "inloop-notes-preview";

/** 新建文章时可选的值，与 Python 侧一致（任务书 §6） */
const TEMPLATES = [
  { value: "paper-note", label: "论文拆解" },
  { value: "build-log", label: "实验日志" },
  { value: "research-note", label: "研究随想" },
  { value: "diary", label: "科研生活" },
  { value: "article", label: "通用文章" },
];

const CATEGORIES = [
  { value: "paper", label: "论文拆解" },
  { value: "code", label: "源码深挖" },
  { value: "build", label: "实验日志" },
  { value: "research", label: "研究随想" },
  { value: "diary", label: "科研生活" },
];

/** 状态的中文标签；值本身保持英文，因为它会写进 front matter */
const STATUS_LABELS: Record<string, string> = {
  idea: "想法",
  researching: "调研中",
  draft: "草稿",
  review: "待审",
  ready: "可发布",
  published: "已发布",
};

export class InloopPreviewView extends ItemView {
  private readonly plugin: InloopPlugin;

  private articlesEl: HTMLElement | null = null;
  private previewEl: HTMLElement | null = null;
  private statusEl: HTMLElement | null = null;
  private buildEl: HTMLElement | null = null;
  private formEl: HTMLElement | null = null;

  constructor(leaf: WorkspaceLeaf, plugin: InloopPlugin) {
    super(leaf);
    this.plugin = plugin;
  }

  getViewType(): string {
    return VIEW_TYPE_INLOOP_PREVIEW;
  }

  getDisplayText(): string {
    return "InLoop 手记";
  }

  getIcon(): string {
    return "newspaper";
  }

  async onOpen(): Promise<void> {
    this.buildLayout();
    await this.render();
  }

  async onClose(): Promise<void> {
    this.contentEl.empty();
  }

  // --- 布局 ---------------------------------------------------------------

  private buildLayout(): void {
    const root = this.contentEl;
    root.empty();
    root.addClass("inloop-panel");

    // 工具栏
    const toolbar = root.createDiv({ cls: "inloop-toolbar" });

    const newBtn = toolbar.createEl("button", { cls: "inloop-btn inloop-btn-primary" });
    setIcon(newBtn.createSpan(), "plus");
    newBtn.createSpan({ text: "新建推文" });
    newBtn.onclick = () => this.showNewArticleForm();

    const refreshBtn = toolbar.createEl("button", { cls: "inloop-btn" });
    setIcon(refreshBtn.createSpan(), "refresh-cw");
    refreshBtn.createSpan({ text: "刷新" });
    refreshBtn.onclick = () => void this.render();

    const copyBtn = toolbar.createEl("button", { cls: "inloop-btn" });
    setIcon(copyBtn.createSpan(), "clipboard-copy");
    copyBtn.createSpan({ text: "构建并复制" });
    copyBtn.onclick = () => void this.plugin.buildAndCopy().then(() => this.renderBuildInfo());

    const openBtn = toolbar.createEl("button", { cls: "inloop-btn" });
    setIcon(openBtn.createSpan(), "external-link");
    openBtn.createSpan({ text: "打开产物" });
    openBtn.onclick = () => {
      const build = this.plugin.getLastBuild();
      if (!build) {
        new Notice("还没有构建产物。先点「构建并复制」。");
        return;
      }
      void this.plugin.openPath(build.html_path);
    };

    this.statusEl = root.createDiv({ cls: "inloop-status" });
    this.formEl = root.createDiv({ cls: "inloop-form" });
    this.formEl.hide();
    this.articlesEl = root.createDiv({ cls: "inloop-articles" });

    root.createDiv({ cls: "inloop-sep" });

    const previewHeader = root.createDiv({ cls: "inloop-preview-header" });
    previewHeader.createSpan({ text: "预览" });
    const openInBrowser = previewHeader.createEl("button", {
      text: "在浏览器打开",
      cls: "inloop-link-btn",
    });
    openInBrowser.onclick = () => {
      const build = this.plugin.getLastBuild();
      if (!build) {
        new Notice("还没有构建产物。先点「构建并复制」。");
        return;
      }
      void this.plugin.openPath(build.preview_path);
    };

    this.buildEl = root.createDiv({ cls: "inloop-build" });

    const previewWrap = root.createDiv({ cls: "inloop-preview-wrap" });
    this.previewEl = previewWrap.createDiv({ cls: "inloop-preview" });
    this.applyPreviewWidth();
  }

  private applyPreviewWidth(): void {
    if (!this.previewEl) return;
    this.previewEl.style.width = `${this.plugin.settings.previewWidth}px`;
  }

  // --- 渲染 ---------------------------------------------------------------

  async render(): Promise<void> {
    this.applyPreviewWidth();
    await Promise.all([this.renderArticles(), this.renderPreview(), this.renderBuildInfo()]);
  }

  private setStatus(text: string, kind: "info" | "error" | "ok" = "info"): void {
    if (!this.statusEl) return;
    this.statusEl.empty();
    this.statusEl.setText(text);
    this.statusEl.toggleClass("inloop-status-error", kind === "error");
    this.statusEl.toggleClass("inloop-status-ok", kind === "ok");
  }

  private async renderArticles(): Promise<void> {
    const host = this.articlesEl;
    if (!host) return;
    host.empty();

    let list;
    try {
      list = await this.plugin.listArticlesSafe();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      host.createDiv({ cls: "inloop-error", text: message });
      host.createDiv({
        cls: "inloop-hint",
        text: "检查插件设置里的「内容目录」与「inloop 可执行文件」。",
      });
      this.setStatus("读取文章列表失败", "error");
      return;
    }

    this.setStatus(`内容目录：${list.content_root}`, "ok");

    if (list.articles.length === 0) {
      host.createDiv({ cls: "inloop-hint", text: "这个内容目录里还没有文章。" });
      host.createDiv({ cls: "inloop-hint", text: "点上面的「新建推文」开始写第一篇。" });
      return;
    }

    const activeSlug = this.plugin.activeSlug();
    for (const article of list.articles) {
      host.appendChild(this.renderArticleRow(article, article.dir_name === activeSlug));
    }
  }

  private renderArticleRow(article: ArticleSummary, isActive: boolean): HTMLElement {
    const row = createDiv({ cls: "inloop-article" });
    row.toggleClass("inloop-article-active", isActive);

    const main = row.createDiv({ cls: "inloop-article-main" });
    const title = main.createDiv({ cls: "inloop-article-title" });
    title.setText(article.parsable ? article.title || "(无标题)" : `${article.dir_name}（无法解析）`);

    const meta = main.createDiv({ cls: "inloop-article-meta" });
    meta.setText(
      [
        article.id ? String(article.id).padStart(3, "0") : "",
        article.category_label,
        article.date,
      ]
        .filter(Boolean)
        .join(" · "),
    );

    const actions = row.createDiv({ cls: "inloop-article-actions" });

    // 状态下拉：切换状态是日常高频动作，做成下拉比"打开文件改 front matter"省事得多。
    // 这也是 Python 侧唯一允许改写文章文件的场景，且只改 status 一行。
    if (article.parsable) {
      const select = actions.createEl("select", { cls: "inloop-status-select" });
      select.title = "切换状态";
      for (const status of STATUSES) {
        const option = select.createEl("option", { value: status, text: STATUS_LABELS[status] });
        if (status === article.status) option.selected = true;
      }
      // 当前状态不在已知列表里（作者手改过）时，补一个只读项，避免下拉显示错值
      if (!(STATUSES as readonly string[]).includes(article.status)) {
        const option = select.createEl("option", {
          value: article.status,
          text: article.status,
        });
        option.selected = true;
      }
      select.onchange = () => {
        void this.changeStatus(article, select.value, select);
      };
    }

    const openBtn = actions.createEl("button", { cls: "inloop-icon-btn", attr: { title: "打开" } });
    setIcon(openBtn, "file-text");
    openBtn.onclick = () => void this.openArticle(article);

    const delBtn = actions.createEl("button", {
      cls: "inloop-icon-btn inloop-danger",
      attr: { title: "删除" },
    });
    setIcon(delBtn, "trash-2");
    delBtn.onclick = () => void this.confirmDelete(article);

    return row;
  }

  /** 切换状态；失败时把下拉恢复成原值，不能让界面显示一个没生效的状态 */
  private async changeStatus(
    article: ArticleSummary,
    status: string,
    select: HTMLSelectElement,
  ): Promise<void> {
    try {
      await this.plugin.setStatusSafe(article.dir_name, status);
      article.status = status;
      new Notice(`✓ ${article.dir_name} → ${status}`);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      new Notice(`切换状态失败：${message}`, 8000);
      select.value = article.status;
    }
  }
  private async openArticle(article: ArticleSummary): Promise<void> {
    const contentRoot = await this.contentRootFromCli();
    const absolute = `${contentRoot}/${article.path}`;
    const vaultPath = toVaultPath(this.app, absolute);
    if (!vaultPath) {
      new Notice(`这篇不在当前 vault 内，请手动打开：${absolute}`);
      return;
    }
    const file = this.app.vault.getAbstractFileByPath(vaultPath);
    if (file) {
      await this.app.workspace.getLeaf().openFile(file as never);
    } else {
      new Notice(`找不到文件：${vaultPath}`);
    }
  }

  /** 从一次 list 调用里拿内容目录（保证与 Python 侧解析结果一致） */
  private async contentRootFromCli(): Promise<string> {
    try {
      const list = await this.plugin.listArticlesSafe();
      return list.content_root.replace(/\\/g, "/");
    } catch {
      return this.plugin.cliOptions().contentRoot?.replace(/\\/g, "/") ?? "";
    }
  }

  private async renderPreview(): Promise<void> {
    const host = this.previewEl;
    if (!host) return;
    host.empty();

    const slug = this.plugin.activeSlug();
    if (!slug) {
      host.createDiv({
        cls: "inloop-hint",
        text: "打开一篇 InLoop 文章（内容目录里的 index.md）后，这里会显示预览。",
      });
      return;
    }

    // 预览方式：用 Python 构建一次，然后加载产物 HTML。
    // 为什么不自己渲染 Markdown：微信端兼容的 CSS 内联在 Python 里，
    // 两套渲染器必然出现"预览好看、粘过去不一样"。
    //
    // 耗时实测：Python 启动约 300ms，构建本身 250–350ms。叠加 400ms 防抖后，
    // 停止输入到看到预览约 0.9–1.0 秒。长文章不是瓶颈（成本被进程启动主导），
    // 因此给出明确的进行中提示，而不是让界面静默停住。
    const busy = host.createDiv({ cls: "inloop-hint inloop-busy", text: "正在渲染…" });
    try {
      const build = await this.plugin.runRaw(["build-wechat", slug]);
      const result = build as unknown as BuildResult;
      const html = await this.readText(result.html_path);
      busy.remove();
      if (html === null) {
        host.createDiv({ cls: "inloop-error", text: `读不到产物：${result.html_path}` });
        return;
      }
      const body = extractBodyHtml(html);
      const frame = host.createEl("iframe", { cls: "inloop-frame" });
      // sandbox 不能为空：空 sandbox 会阻止一切 file:// 加载，图片全成坏图。
      // allow-same-origin 不授予脚本执行权限，仍能隔离样式。
      frame.setAttribute("sandbox", FRAME_SANDBOX);
      // base 指向产物目录：产物里的图片是相对路径，没有它就会相对 Obsidian 的
      // app:// 基址解析而全部失败。
      frame.srcdoc = wrapForFrame(body, frameBaseHref(result.output_dir));
    } catch (error) {
      busy.remove();
      const message = error instanceof Error ? error.message : String(error);
      host.createDiv({ cls: "inloop-error", text: `预览失败：${message}` });
    }
  }

  private async renderBuildInfo(): Promise<void> {
    const host = this.buildEl;
    if (!host) return;
    host.empty();

    const build = this.plugin.getLastBuild();
    if (!build) {
      host.createDiv({ cls: "inloop-hint", text: "尚未构建。" });
      return;
    }
    host.createDiv({ cls: "inloop-hint", text: `产物目录：${build.output_dir}` });
    if (build.body_images.length === 0) {
      host.createDiv({ cls: "inloop-hint", text: "本文没有正文图片。" });
      return;
    }
    host.createDiv({
      cls: "inloop-hint",
      text: `正文图片 ${build.body_images.length} 张，需在微信编辑器里逐张上传：`,
    });
    for (const image of build.body_images) {
      const line = host.createDiv({ cls: "inloop-image-line" });
      const where = image.section ? `「${image.section}」一节内` : "正文开头处";
      line.setText(`第 ${image.order} 张  ${image.output}  → ${where}`);
    }
  }

  private async readText(path: string): Promise<string | null> {
    try {
      const { readFile } = await import("node:fs/promises");
      return await readFile(path, "utf8");
    } catch {
      return null;
    }
  }

  // --- 新建表单 -----------------------------------------------------------

  showNewArticleForm(): void {
    const form = this.formEl;
    if (!form) return;
    form.empty();
    form.show();

    form.createEl("h4", { text: "新建推文" });

    const title = this.field(form, "标题", "文章标题");
    const slug = this.field(form, "英文短名", "例如 light-o1（只用小写字母、数字、连字符）");

    const templateRow = form.createDiv({ cls: "inloop-field" });
    templateRow.createEl("label", { text: "模板" });
    const templateSelect = templateRow.createEl("select");
    for (const item of TEMPLATES) {
      templateSelect.createEl("option", { value: item.value, text: item.label });
    }

    const categoryRow = form.createDiv({ cls: "inloop-field" });
    categoryRow.createEl("label", { text: "栏目" });
    const categorySelect = categoryRow.createEl("select");
    for (const item of CATEGORIES) {
      categorySelect.createEl("option", { value: item.value, text: item.label });
    }

    const tags = this.field(form, "标签", "逗号分隔，至少一个");
    const summary = this.field(form, "摘要", "一句话，发布时要用");

    const actions = form.createDiv({ cls: "inloop-form-actions" });
    const submit = actions.createEl("button", { text: "创建", cls: "inloop-btn inloop-btn-primary" });
    const cancel = actions.createEl("button", { text: "取消", cls: "inloop-btn" });

    cancel.onclick = () => {
      form.hide();
      form.empty();
    };

    submit.onclick = () => {
      void (async () => {
        const payload = {
          title: title.value.trim(),
          slug: slug.value.trim(),
          template: templateSelect.value,
          category: categorySelect.value,
          tags: tags.value.trim(),
          summary: summary.value.trim(),
        };
        if (!payload.title || !payload.slug) {
          new Notice("标题与英文短名都必须填。");
          return;
        }
        submit.disabled = true;
        try {
          const path = await this.plugin.createArticleFromForm(payload);
          form.hide();
          form.empty();
          new Notice(`✓ 已创建 ${path}`);
          await this.render();
          await this.openByRelativePath(path);
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          new Notice(`创建失败：${message}`, 10000);
        } finally {
          submit.disabled = false;
        }
      })();
    };
  }

  private field(host: HTMLElement, label: string, placeholder: string): HTMLInputElement {
    const row = host.createDiv({ cls: "inloop-field" });
    row.createEl("label", { text: label });
    const input = row.createEl("input", { type: "text" });
    input.placeholder = placeholder;
    return input;
  }

  /** 创建后立刻打开，省掉"去文件树里找"这一步 */
  private async openByRelativePath(relativePath: string): Promise<void> {
    const file = this.app.vault.getAbstractFileByPath(relativePath);
    if (file) {
      await this.app.workspace.getLeaf().openFile(file as never);
      return;
    }
    new Notice(`已创建，但没能在 vault 里定位到：${relativePath}`);
  }

  // --- 删除 ---------------------------------------------------------------

  private async confirmDelete(article: ArticleSummary): Promise<void> {
    // 破坏性操作，先让用户看清楚删的是什么、会连带删掉几张图
    const label = article.parsable ? article.title : article.dir_name;
    const images = await this.imageCountFor(article);
    const detail = images > 0 ? `（含 ${images} 张图片）` : "";
    const ok = window.confirm(`确定删除《${label}》${detail}？\n\n此操作不可撤销。`);
    if (!ok) return;

    try {
      const result = await this.plugin.deleteArticleSafe(article.dir_name);
      const removed = (result as { removed?: boolean }).removed;
      if (removed === false) {
        new Notice("删除被取消。");
      } else {
        new Notice(`✓ 已删除 ${article.dir_name}`);
      }
      await this.render();
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      new Notice(`删除失败：${message}`, 10000);
    }
  }

  /** 数一篇文里有多少图片（用 metadata 清单，不重复实现统计逻辑） */
  private async imageCountFor(article: ArticleSummary): Promise<number> {
    try {
      const result = (await this.plugin.runRaw(["build-wechat", article.dir_name])) as unknown as
        | BuildResult
        | undefined;
      const images: ImageEntry[] = result?.images ?? [];
      return images.filter((entry) => entry.kind === "body").length;
    } catch {
      return 0;
    }
  }
}

