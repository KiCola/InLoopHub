/**
 * 插件设置。
 *
 * 设计取向：**能自动探测的就不要让用户填。**
 * 用户只需要在必要时覆盖，因此设置界面会显示当前探测结果，
 * 让"到底用的是哪个路径"一眼可见——路径错配是这类工具最常见的故障。
 */

import { App, Notice, PluginSettingTab, Setting, normalizePath } from "obsidian";
import type InloopPlugin from "./main";
import { guessExecutable } from "./inloop/cli";
import { vaultBasePath } from "./obsidian-env";

/**
 * 内容目录名：vault 根下的这个文件夹用来放文章。
 *
 * 与工具仓库的兜底目录名保持一致，避免"设置里显示一个名字、CLI 找另一个"。
 */
export const DEFAULT_CONTENT_DIR_NAME = "content";

/**
 * vault 里的工具指向文件（相对 vault 根）。
 *
 * 为什么需要它：工具仓库与 vault 可以位于**不同的盘**（本机就是：vault 在 C、
 * 工具在 E）。这种情况无法靠"逐级向上搜索"发现，必须有人告诉插件一次。
 *
 * 把这个路径存在 **vault 内**而不是插件设置里，有两个好处：
 * 1. 它在坚果云同步范围内 → 换电脑、重装 Obsidian、重装插件都不用重填
 * 2. 它是纯文本 → 出问题时能直接打开看，不藏在插件数据里
 */
export const POINTER_FILE_NAME = "inloop-path.txt";

/** 从 vault 里的指向文件读工具仓库路径；没有则返回空串 */
export async function readPointerFile(app: App): Promise<string> {
  try {
    const file = app.vault.getAbstractFileByPath(normalizePath(POINTER_FILE_NAME));
    if (!file) return "";
    const content = await app.vault.cachedRead(file as never);
    return firstMeaningfulLine(content);
  } catch {
    return "";
  }
}

/**
 * 取第一行有意义的内容。
 *
 * 允许文件里写注释（`#` 开头）与空行——这个文件是给人看的，
 * 应当能顺便记录"这是什么"。
 */
export function firstMeaningfulLine(content: string): string {
  for (const raw of content.split(/\r?\n/)) {
    const line = raw.trim();
    if (line && !line.startsWith("#")) return line;
  }
  return "";
}

/** 把工具仓库路径写进 vault 的指向文件 */
export async function writePointerFile(app: App, repoRoot: string): Promise<void> {
  const body = [
    "# InLoop 手记：工具仓库的位置",
    "#",
    "# 这一行是插件要用的路径（含 config/ 与 styles/ 的目录）。",
    "# 放在 vault 里是为了随坚果云同步：换电脑或重装插件都不必重填。",
    "#",
    repoRoot,
    "",
  ].join("\n");
  const path = normalizePath(POINTER_FILE_NAME);
  const existing = app.vault.getAbstractFileByPath(path);
  if (existing) {
    await app.vault.modify(existing as never, body);
  } else {
    await app.vault.create(path, body);
  }
}

export interface InloopSettings {
  /** inloop 可执行文件路径；留空则自动探测 */
  executable: string;
  /** 工具仓库根（含 config/）；留空则自动探测 */
  repoRoot: string;
  /** 内容目录（放文章的地方）；留空则默认 <vault>/InLoopPub */
  contentRoot: string;
  /** 正文预览区的宽度（像素），模拟手机阅读宽度 */
  previewWidth: number;
  /** 编辑停止多久后重新渲染（毫秒）。太小会卡，太大会觉得迟钝 */
  previewDebounceMs: number;
}

export const DEFAULT_SETTINGS: InloopSettings = {
  executable: "",
  repoRoot: "",
  contentRoot: "",
  previewWidth: 430,
  previewDebounceMs: 400,
};

/**
 * 探测工具仓库根。
 *
 * 线索按可靠性排序：用户配置 > 环境变量 > 从找到的 `inloop` 位置反推。
 *
 * 可执行文件通常位于 `<repo>/.venv/Scripts/inloop.exe`，
 * 因此向上三级即仓库根（Scripts → .venv → repo）。
 */
/**
 * 工具仓库根的缓存。
 *
 * 指向文件是异步读的，而 `detectRepoRoot` 被渲染路径同步调用（会随每次预览触发），
 * 因此必须缓存。写入时会主动失效，保证设置改动立刻生效。
 */
let cachedPointerRepoRoot: string | null = null;

/** 让指向文件缓存失效（写文件或改设置后调用） */
export function invalidateRepoRootCache(): void {
  cachedPointerRepoRoot = null;
}

/** 预读指向文件并填入缓存；插件启动时调用一次，之后同步读缓存 */
export async function warmRepoRootCache(app: App): Promise<string> {
  cachedPointerRepoRoot = await readPointerFile(app);
  return cachedPointerRepoRoot;
}

/**
 * 探测工具仓库根。
 *
 * 线索按可靠性排序：
 * 1. 插件设置里填的
 * 2. 环境变量 `INLOOP_ROOT`
 * 3. **vault 里的 `inloop-path.txt`**（随坚果云同步，换电脑不必重填）
 * 4. 从找得到的 `inloop` 反推（可执行文件通常在 `<repo>/.venv/Scripts/inloop.exe`）
 */
export function detectRepoRoot(app: App, settings: InloopSettings): string {
  if (settings.repoRoot.trim()) return settings.repoRoot.trim();

  const fromEnv = process.env.INLOOP_ROOT;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();

  if (cachedPointerRepoRoot && cachedPointerRepoRoot.trim()) {
    return cachedPointerRepoRoot.trim();
  }

  return repoRootFromExecutable(resolveExecutable(app, settings));
}

/** 从可执行文件路径反推工具仓库根；推不出来时返回空串 */
export function repoRootFromExecutable(executable: string): string {
  const normalized = (executable || "").replace(/\\/g, "/");
  const index = normalized.lastIndexOf("/.venv/");
  return index > 0 ? normalized.slice(0, index) : "";
}

/**
 * 解析实际使用的可执行文件路径。
 *
 * **鸡生蛋问题**：仓库根是从可执行文件路径反推的，而无配置时又需要一个仓库根
 * 才能拼出可执行文件路径。解法有两条：
 *
 * 1. 让 `guessExecutable` 主动**搜索**若干候选位置（见 `inloop/cli.ts`），
 *    而不是只会在 PATH 上找一个叫 `inloop` 的命令
 * 2. 允许把仓库路径写进 vault 的指向文件（跨盘场景下唯一可行的自动发现方式）
 *
 * 两条都不成立时（本机就是：vault 在 C、工具在 E），会返回 "inloop" 并由
 * 调用方给出"去哪里填"的指引——报错信息里会带上建议的绝对路径。
 */
export function resolveExecutable(app: App, settings: InloopSettings): string {
  if (settings.executable.trim()) return settings.executable.trim();

  // 仓库根已知（设置/环境变量/指向文件）就直接拼
  const repoRoot = detectRepoRoot(app, settings);
  if (repoRoot) {
    const fromRepo = guessExecutable("", repoRoot);
    if (fromRepo !== "inloop") return fromRepo;
  }

  // 否则在 vault 及其附近搜索
  return guessExecutable("", vaultBasePath(app));
}

/** 解析实际使用的内容目录 */
export function resolveContentRoot(app: App, settings: InloopSettings): string {
  if (settings.contentRoot.trim()) return settings.contentRoot.trim();
  const fromEnv = process.env.INLOOP_CONTENT;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  return `${vaultBasePath(app)}/${DEFAULT_CONTENT_DIR_NAME}`;
}

export class InloopSettingTab extends PluginSettingTab {
  private readonly plugin: InloopPlugin;

  constructor(app: App, plugin: InloopPlugin) {
    super(app, plugin);
    this.plugin = plugin;
  }

  display(): void {
    const { containerEl } = this;
    containerEl.empty();
    containerEl.createEl("h2", { text: "InLoop 手记" });

    const executable = resolveExecutable(this.app, this.plugin.settings);
    const repoRoot = detectRepoRoot(this.app, this.plugin.settings);
    const executableFound = executable !== "inloop";

    // 找不到内核时，把"你该填什么"直接写出来。
    // 只报"找不到"而不给具体值，用户只能去猜——这是实测踩到的问题。
    if (!executableFound) {
      const warn = containerEl.createDiv({ cls: "inloop-setup-warning" });
      warn.createEl("strong", { text: "还需要填一项才能用" });
      warn.createEl("p", {
        text:
          "插件没找到 inloop。它通常装在工具仓库的虚拟环境里、不在系统 PATH 上，" +
          "因此需要你告诉插件一次。在下面「工具仓库根目录」里填入工具仓库位置即可" +
          "（例如 E:/InLoopHub）。",
      });
      warn.createEl("p", {
        text:
          "填好后点「记住到 vault」，路径会存进 vault 的 inloop-path.txt，" +
          "随坚果云同步——换电脑或重装插件都不用再填。",
      });
    }

    containerEl.createEl("p", {
      text:
        "插件只做界面，渲染与校验仍由 Python 工具 inloop 完成。" +
        "下面各项留空时会自动探测，实际使用的值显示在每一栏下方。",
      cls: "setting-item-description",
    });

    new Setting(containerEl)
      .setName("工具仓库根目录")
      .setDesc(
        `当前使用：${repoRoot || "（未探测到）"}` +
          "　—　含 config/ 与 styles/ 的目录",
      )
      .addText((text) =>
        text
          .setPlaceholder("E:/InLoopHub")
          .setValue(this.plugin.settings.repoRoot)
          .onChange(async (value) => {
            this.plugin.settings.repoRoot = value;
            await this.plugin.saveSettings();
            this.plugin.refreshDetectionCache();
            this.display();
          }),
      )
      .addButton((button) =>
        button.setButtonText("记住到 vault").onClick(async () => {
          if (!repoRoot) {
            new Notice("还没探测到有效路径，请先在上面填入工具仓库根目录。");
            return;
          }
          await this.plugin.rememberRepoRoot(repoRoot);
          new Notice(`✓ 已记住：${repoRoot}\n（写入 vault 的 ${POINTER_FILE_NAME}）`);
          this.display();
        }),
      );

    new Setting(containerEl)
      .setName("inloop 可执行文件")
      .setDesc(
        executableFound
          ? `当前使用：${executable}`
          : `未探测到（会尝试调用 PATH 上的 ${executable}）。通常不必手填——` +
            "填好上面的「工具仓库根目录」就够了。",
      )
      .addText((text) =>
        text
          .setPlaceholder("<工具仓库>/.venv/Scripts/inloop.exe")
          .setValue(this.plugin.settings.executable)
          .onChange(async (value) => {
            this.plugin.settings.executable = value;
            await this.plugin.saveSettings();
            this.plugin.refreshDetectionCache();
            this.display();
          }),
      );

    new Setting(containerEl)
      .setName("内容目录")
      .setDesc(
        `当前使用：${resolveContentRoot(this.app, this.plugin.settings)}` +
          "　—　文章存放位置",
      )
      .addText((text) =>
        text
          .setPlaceholder(`${vaultBasePath(this.app)}/${DEFAULT_CONTENT_DIR_NAME}`)
          .setValue(this.plugin.settings.contentRoot)
          .onChange(async (value) => {
            this.plugin.settings.contentRoot = value;
            await this.plugin.saveSettings();
            this.display();
          }),
      );

    new Setting(containerEl)
      .setName("预览宽度")
      .setDesc("模拟手机阅读宽度，公众号正文常用 430px")
      .addSlider((slider) =>
        slider
          .setLimits(320, 600, 10)
          .setValue(this.plugin.settings.previewWidth)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.previewWidth = value;
            await this.plugin.saveSettings();
            this.plugin.refreshPreview();
          }),
      );

    new Setting(containerEl)
      .setName("实时预览延迟")
      .setDesc("停止输入多久后重新渲染（毫秒）。渲染有成本，太小会让打字变卡。")
      .addSlider((slider) =>
        slider
          .setLimits(150, 1500, 50)
          .setValue(this.plugin.settings.previewDebounceMs)
          .setDynamicTooltip()
          .onChange(async (value) => {
            this.plugin.settings.previewDebounceMs = value;
            await this.plugin.saveSettings();
          }),
      );
  }
}
