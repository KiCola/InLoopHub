/**
 * 面板样式。
 *
 * 为什么用注入 `<style>` 而不是 `styles.css` 文件：
 * Obsidian 只自动加载插件目录下的 `styles.css`，那会多一个产物文件需要
 * 与 main.js 同步部署。这里选择在插件加载时注入，产物就只有两个文件
 * （main.js + manifest.json），部署更不易出错。
 *
 * 颜色一律用 Obsidian 的 CSS 变量（`--text-normal` 等），
 * 这样明暗主题都能跟随，不必维护两套。
 */

const STYLE_ID = "inloop-notes-styles";

const CSS = `
/* 面板整体用纵向布局，让预览区能占据剩余高度而不是被列表挤出去 */
.inloop-panel {
  padding: 8px 10px 20px 10px;
  font-size: 13px;
  display: flex;
  flex-direction: column;
  height: 100%;
  overflow-y: auto;
}

/*
 * 文章列表限高并独立滚动。
 * 不这么做时，文章一多就会把下面的预览区推出可视范围——
 * 用户看到的是"面板里没有预览"，会以为功能不存在。
 */
.inloop-list-wrap {
  max-height: 32vh;
  overflow-y: auto;
  flex: 0 0 auto;
}

.inloop-toolbar {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}

.inloop-btn {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  padding: 4px 10px;
  border: 1px solid var(--background-modifier-border);
  border-radius: 6px;
  background: var(--interactive-normal);
  color: var(--text-normal);
  cursor: pointer;
  font-size: 12px;
}
.inloop-btn:hover { background: var(--interactive-hover); }
.inloop-btn:disabled { opacity: 0.5; cursor: default; }
.inloop-btn-primary {
  background: var(--interactive-accent);
  color: var(--text-on-accent);
  border-color: var(--interactive-accent);
}

.inloop-status {
  font-size: 11px;
  color: var(--text-muted);
  margin-bottom: 6px;
  word-break: break-all;
}
.inloop-status-ok { color: var(--text-muted); }
.inloop-status-error { color: var(--text-error); }

.inloop-articles { display: flex; flex-direction: column; gap: 2px; }

.inloop-article {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 5px 6px;
  border-radius: 6px;
}
.inloop-article:hover { background: var(--background-modifier-hover); }
.inloop-article-active {
  background: var(--background-modifier-active-hover);
  box-shadow: inset 2px 0 0 var(--interactive-accent);
}
.inloop-article-main { flex: 1; min-width: 0; }
.inloop-article-title {
  font-weight: 600;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.inloop-article-meta { font-size: 11px; color: var(--text-muted); }
.inloop-article-actions { display: flex; gap: 2px; align-items: center; }

.inloop-status-select {
  font-size: 10px;
  padding: 2px 4px;
  border: 1px solid var(--background-modifier-border);
  border-radius: 4px;
  background: var(--background-primary);
  color: var(--text-muted);
  cursor: pointer;
  max-width: 68px;
}
.inloop-status-select:hover { color: var(--text-normal); }

.inloop-icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  padding: 0;
  border: none;
  border-radius: 5px;
  background: transparent;
  color: var(--text-muted);
  cursor: pointer;
}
.inloop-icon-btn:hover { background: var(--background-modifier-hover); color: var(--text-normal); }
.inloop-danger:hover { color: var(--text-error); }

.inloop-sep {
  height: 1px;
  background: var(--background-modifier-border);
  margin: 10px 0;
}

.inloop-preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 600;
  margin-bottom: 6px;
}
.inloop-link-btn {
  border: none;
  background: transparent;
  color: var(--text-accent);
  cursor: pointer;
  font-size: 11px;
}
.inloop-link-btn:hover { text-decoration: underline; }

.inloop-build { margin-bottom: 8px; }
.inloop-image-line {
  font-size: 11px;
  color: var(--text-normal);
  padding-left: 8px;
  font-family: var(--font-monospace);
}

.inloop-preview-wrap { display: flex; justify-content: center; }
.inloop-preview {
  max-width: 100%;
  border: 1px solid var(--background-modifier-border);
  border-radius: 8px;
  overflow: hidden;
  background: #fff;
}
.inloop-frame {
  display: block;
  width: 100%;
  height: 46vh;
  min-height: 260px;
  border: none;
  background: #fff;
}

.inloop-hint { font-size: 11px; color: var(--text-muted); line-height: 1.7; }
.inloop-busy { color: var(--text-accent); }

/* 设置界面里"还需要填一项"的提示。要显眼——用户卡在这一步就没法用插件。 */
.inloop-setup-warning {
  border: 1px solid var(--text-warning, #d97706);
  border-left-width: 3px;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 12px;
  background: var(--background-secondary);
}
.inloop-setup-warning strong { display: block; margin-bottom: 4px; }
.inloop-setup-warning p { margin: 4px 0; font-size: 12px; line-height: 1.7; }

.inloop-error {
  font-size: 12px;
  color: var(--text-error);
  white-space: pre-wrap;
  word-break: break-word;
}

.inloop-form {
  border: 1px solid var(--background-modifier-border);
  border-radius: 8px;
  padding: 10px;
  margin-bottom: 10px;
}
.inloop-form h4 { margin: 0 0 8px 0; }
.inloop-field { display: flex; flex-direction: column; gap: 3px; margin-bottom: 8px; }
.inloop-field label { font-size: 11px; color: var(--text-muted); }
.inloop-field input,
.inloop-field select {
  width: 100%;
  padding: 4px 6px;
  border: 1px solid var(--background-modifier-border);
  border-radius: 5px;
  background: var(--background-primary);
  color: var(--text-normal);
}
.inloop-form-actions { display: flex; gap: 6px; margin-top: 4px; }
`;

/** 把样式注入文档；重复调用不会重复插入 */
export function installStyles(): void {
  if (document.getElementById(STYLE_ID)) return;
  const style = document.createElement("style");
  style.id = STYLE_ID;
  style.textContent = CSS;
  document.head.appendChild(style);
}
