/** 发布排版表单；只保存独立配置，不操作编辑器字体或文章正文。 */
export type TypographySettings = Record<string, string | number>;

export interface TypographyResult {
  ok: boolean;
  schema: number;
  global: TypographySettings;
  article: TypographySettings;
  effective: TypographySettings;
  fonts: Record<string, string>;
  font_choices: Record<string, string[]>;
  fields: Record<string, { min: number; max: number; step: number; label: string }>;
}

interface TypographyActions {
  load(target: string): Promise<TypographyResult>;
  save(target: string, values: TypographySettings, globalScope: boolean): Promise<TypographyResult>;
}

let nextFontListId = 0;

export class TypographyPanel {
  private readonly details: HTMLDetailsElement;
  private readonly body: HTMLElement;
  private target = "";
  private version = 0;
  private scope: "article" | "global" = "article";
  private data: TypographyResult | null = null;
  private inputs = new Map<string, HTMLInputElement | HTMLSelectElement>();
  private message: HTMLElement | null = null;
  private fieldset: HTMLFieldSetElement | null = null;

  constructor(host: HTMLElement, private readonly actions: TypographyActions) {
    this.details = host.createEl("details", { cls: "inloop-typography" });
    this.details.createEl("summary", { text: "发布排版" });
    this.body = this.details.createDiv();
    this.details.ontoggle = () => {
      if (this.details.open) void this.load();
    };
  }

  async update(target: string): Promise<void> {
    if (target === this.target) return;
    this.target = target;
    this.scope = "article";
    this.version += 1;
    this.data = null;
    this.inputs.clear();
    this.fieldset = null;
    this.body.empty();
    if (!target) this.body.setText("请先选择文章。");
    else if (this.details.open) await this.load();
  }

  private async load(): Promise<void> {
    // 保存尚在构建队列中时，重新展开不能用磁盘旧值覆盖待保存的表单。
    if (this.fieldset?.disabled) return;
    if (!this.target) {
      this.body.setText("请先选择文章。");
      return;
    }
    const version = ++this.version;
    this.inputs.clear();
    this.body.setText("正在读取发布排版…");
    try {
      const data = await this.actions.load(this.target);
      if (version !== this.version) return;
      this.data = data;
      this.render();
    } catch (error) {
      if (version === this.version) this.body.setText(`读取失败：${String(error)}`);
    }
  }

  private render(): void {
    const data = this.data;
    if (!data) return;
    this.body.empty();
    this.inputs.clear();
    const fieldset = this.body.createEl("fieldset");
    this.fieldset = fieldset;
    const scopeLabel = fieldset.createEl("label", { cls: "inloop-type-row" });
    scopeLabel.createSpan({ text: "应用范围" });
    const scope = scopeLabel.createEl("select");
    scope.createEl("option", { value: "article", text: "当前文章" });
    scope.createEl("option", { value: "global", text: "全局默认" });
    scope.value = this.scope;
    scope.onchange = () => {
      this.scope = scope.value as "article" | "global";
      this.render();
    };
    fieldset.createDiv({ cls: "inloop-hint", text: this.scope === "article"
      ? "留空沿用全局或主题。切换文章会丢弃未应用输入。"
      : "影响未单独覆盖的文章；当前文章的单独设置仍优先。" });
    const values = data[this.scope];
    for (const [key, labelText] of [["font_zh", "中文字体"], ["font_en", "英文字体"]] as const) {
      const label = fieldset.createEl("label", { cls: "inloop-type-row" });
      label.createSpan({ text: labelText });
      const font = label.createEl("input", { type: "text" });
      const listId = `inloop-font-list-${++nextFontListId}`;
      font.setAttribute("list", listId);
      font.maxLength = 80;
      const inherited = this.scope === "article" ? data.global[key] : undefined;
      font.placeholder = inherited ? `继承：${inherited}` : "继承原设置；可输入字体名";
      font.value = String(values[key] ?? "");
      const choices = label.createEl("datalist", { attr: { id: listId } });
      for (const value of data.font_choices[key] ?? []) choices.createEl("option", { value });
      this.inputs.set(key, font);
    }
    fieldset.createDiv({ cls: "inloop-hint", text: "例如中文填“楷体”，英文填“Times New Roman”。可选候选或输入其他字体名；设备未安装时会回退。" });
    for (const [key, definition] of Object.entries(data.fields)) {
      const label = fieldset.createEl("label", { cls: "inloop-type-row" });
      label.createSpan({ text: definition.label });
      const input = label.createEl("input", { type: "number" });
      input.min = String(definition.min);
      input.max = String(definition.max);
      input.step = String(definition.step);
      const inherited = this.scope === "article" ? data.global[key] : undefined;
      input.placeholder = inherited === undefined ? "继承主题" : `继承：${inherited}`;
      input.value = String(values[key] ?? "");
      this.inputs.set(key, input);
    }
    fieldset.createDiv({ cls: "inloop-hint", text: "主标题控制 h1，后续标题逐级递减。代码保持等宽；手机字体以微信预览为准。" });
    const buttons = fieldset.createDiv({ cls: "inloop-toolbar" });
    buttons.createEl("button", { text: "应用并刷新", cls: "inloop-btn inloop-btn-primary" })
      .onclick = () => void this.apply(false);
    buttons.createEl("button", { text: "恢复继承", cls: "inloop-btn" })
      .onclick = () => void this.apply(true);
    this.message = this.body.createDiv({ cls: "inloop-hint" });
  }

  private async apply(reset: boolean): Promise<void> {
    if (!this.target || !this.fieldset || this.fieldset.disabled) return;
    const values: TypographySettings = {};
    if (!reset) {
      // 旧版风格保留为回退，避免仅改字号时丢失已有字体选择。
      const legacy = this.data?.[this.scope].font_family;
      if (legacy) values.font_family = legacy;
      for (const [key, input] of this.inputs) {
        if (!input.value.trim()) continue;
        const isFont = key === "font_zh" || key === "font_en";
        if (!isFont && !input.checkValidity()) {
          this.message?.setText(`请检查${this.data?.fields[key]?.label}的范围与步长。`);
          return;
        }
        values[key] = isFont ? input.value.trim() : Number(input.value);
      }
    }
    const version = this.version;
    this.fieldset.disabled = true;
    this.message?.setText("正在保存…");
    try {
      const data = await this.actions.save(this.target, values, this.scope === "global");
      if (version !== this.version) return;
      this.data = data;
      this.render();
      this.message?.setText("已保存，正在刷新预览。已有微信草稿需重新上传。 ");
    } catch (error) {
      if (version === this.version) this.message?.setText(`保存失败：${String(error)}`);
    } finally {
      if (version === this.version && this.fieldset) this.fieldset.disabled = false;
    }
  }
}
