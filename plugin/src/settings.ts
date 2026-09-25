/**
 * 插件设置。
 *
 * 设计取向：**能自动探测的就不要让用户填。**
 * 用户只需要在必要时覆盖，因此设置界面会显示当前探测结果，
 * 让"到底用的是哪个路径"一眼可见——路径错配是这类工具最常见的故障。
 */

import { App, PluginSettingTab, Setting } from "obsidian";
import type InloopPlugin from "./main";
import { guessExecutable } from "./inloop/cli";
import { vaultBasePath } from "./obsidian-env";

/** 内容目录名：vault 根下的这个文件夹用来放文章 */
export const DEFAULT_CONTENT_DIR_NAME = "InLoopPub";

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
 * 线索按可靠性排序：用户配置 > 环境变量 > 可执行文件所在位置反推。
 * 可执行文件通常位于 `<repo>/.venv/Scripts/inloop.exe`，
 * 因此向上三级即仓库根（Scripts → .venv → repo）。
 */
export function detectRepoRoot(app: App, settings: InloopSettings): string {
  if (settings.repoRoot.trim()) return settings.repoRoot.trim();

  const fromEnv = process.env.INLOOP_ROOT;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();

  const executable = resolveExecutable(app, settings);
  if (executable) {
    const normalized = executable.replace(/\\/g, "/");
    const marker = "/.venv/";
    const index = normalized.lastIndexOf(marker);
    if (index > 0) return normalized.slice(0, index);
  }
  return "";
}

/** 解析实际使用的可执行文件路径 */
export function resolveExecutable(app: App, settings: InloopSettings): string {
  return guessExecutable(settings.executable, detectRepoRootRaw(app, settings));
}

/** 只从环境变量与配置探测仓库根，不递归调用 resolveExecutable */
function detectRepoRootRaw(_app: App, settings: InloopSettings): string {
  if (settings.repoRoot.trim()) return settings.repoRoot.trim();
  const fromEnv = process.env.INLOOP_ROOT;
  if (fromEnv && fromEnv.trim()) return fromEnv.trim();
  return "";
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

    containerEl.createEl("p", {
      text:
        "插件只做界面，渲染与校验仍由 Python 工具 inloop 完成。" +
        "下面三项留空时会自动探测，探测结果见每一栏下方的灰色说明。",
      cls: "setting-item-description",
    });

    new Setting(containerEl)
      .setName("inloop 可执行文件")
      .setDesc(`当前使用：${resolveExecutable(this.app, this.plugin.settings) || "（未探测到）"}`)
      .addText((text) =>
        text
          .setPlaceholder("<工具仓库>/.venv/Scripts/inloop.exe")
          .setValue(this.plugin.settings.executable)
          .onChange(async (value) => {
            this.plugin.settings.executable = value;
            await this.plugin.saveSettings();
            this.display();
          }),
      );

    new Setting(containerEl)
      .setName("工具仓库根目录")
      .setDesc(
        `当前使用：${detectRepoRoot(this.app, this.plugin.settings) || "（未探测到）"}` +
          "　—　含 config/ 与 styles/ 的目录",
      )
      .addText((text) =>
        text
          .setPlaceholder("E:/InLoopHub")
          .setValue(this.plugin.settings.repoRoot)
          .onChange(async (value) => {
            this.plugin.settings.repoRoot = value;
            await this.plugin.saveSettings();
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
