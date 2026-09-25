# InLoop 手记 · Obsidian 插件

在你的 Obsidian vault 里管理 InLoop 手记的推文：**新建、实时预览、构建并复制到微信公众号**。

## 这个插件做什么，不做什么

**做**：界面。文章列表、新建表单、实时渲染预览、一键把正文 HTML 放进剪贴板、删除、状态。

**不做**：渲染。CSS 内联、语法着色、图片处理、内容校验**全部仍在 Python 工具 `inloop` 里**。

为什么这样分：渲染逻辑已经实现并有 200 多项测试覆盖。用 TypeScript 再写一套，
就会出现"预览好看、粘到公众号不一样"——两套渲染器必然漂移。

**代价**：你的机器上要有 Python 与 `inloop`。这是本插件唯一的安装负担。

## 前置条件

1. **Python 3.11+**
2. **InLoop 工具已安装**：

   ```bash
   cd <工具仓库>
   python -m venv .venv
   .venv/Scripts/python.exe -m pip install --no-build-isolation -e ".[dev]"
   ```

   验证：`.venv/Scripts/inloop.exe version` 有输出即成功。

## 安装

```bash
cd <工具仓库>/plugin
npm install
npm run build
npm run install-to-vault -- --vault "C:/path/to/your/vault"
```

`install-to-vault` 会在 vault 的 `.obsidian/plugins/` 下建立一个**目录联接**指向
本仓库的 `plugin/dist/`。这样改代码后重新 `npm run build` 即可生效，不必手工复制；
vault 里也不会多出 `node_modules` 之类的构建中间物（如果你把 vault 放在同步盘里，
这一点很重要）。

然后在 Obsidian 里：**设置 → 第三方插件 → 刷新 → 启用「InLoop 手记」**。
列表里看不到就重启一次 Obsidian。

## 配置

**通常只需要填一项**：打开设置，看第一栏「工具仓库根目录」是不是空的。
如果是，填入工具仓库位置（例如 `E:/InLoopHub`），然后点「记住到 vault」。

### 为什么需要手填这一项

`inloop` 是 `pip install -e` 装进**工具仓库的虚拟环境**里的，通常不在系统 PATH 上。
插件要调用它就必须知道工具仓库在哪。自动探测按以下顺序尝试：

1. 设置里填的「工具仓库根目录」
2. 环境变量 `INLOOP_ROOT`
3. **vault 里的 `inloop-path.txt`**
4. 从 vault 目录逐级向上找 `.venv/Scripts/inloop.exe`

第 4 条只在"工具仓库恰好是 vault 的上级目录"时有效。
**如果工具仓库和 vault 在不同的盘**（例如 vault 在 C、工具在 E），
前三条之外无法自动发现，必须由人告诉一次——这不是缺陷，是路径的现实。

### 内容目录在 vault 之外？用联接接进来

内容与工具解耦之后，文章常在 vault **之外**（另一个盘、另一个目录）。
这样 Obsidian **打不开**它们——它只认 vault 内的文件。

**解法：用目录联接把内容目录挂进 vault。** 文件实际仍在原处，不是拷贝：

```bash
cd plugin
npm run link-content -- --content "E:/InLoopHub/content"
```

它会在 vault 里建一个 `InLoopContent/` 指向内容目录，然后：

1. 把插件的「内容目录」设为 **vault 内那个路径**
   （脚本会把完整路径打印出来，直接复制）
2. 在 Obsidian 里刷新文件树或重启

之后文章就像普通笔记一样：文件树能看到、能点开编辑、**实时预览照常工作**。

> **实测确认 Obsidian 会索引联接里的文件**：`workspace.json` 的 `lastOpenFiles`
> 里出现过 `InLoopContent/2026/001-.../index.md`，即用户确实在 Obsidian 里
> 打开过它们。
>
> 为什么用联接而不是拷贝：不占双份空间，也不会让同步盘同步一份工具仓库的内容。
> 删掉联接不会删文章。

移除联接：`npm run link-content -- --remove`。

### `inloop-path.txt`：让这次告知只做一次

点「记住到 vault」会在 **vault 根目录**写入 `inloop-path.txt`：

```
# InLoop 手记：工具仓库的位置
#
# 这一行是插件要用的路径（含 config/ 与 styles/ 的目录）。
#
E:/InLoopHub
```

放在 vault 里而不是插件设置里，是因为它**随坚果云同步**：
换电脑、重装 Obsidian、重装插件都不用重填。同时它是纯文本，出问题能直接打开看。

### 各项设置

| 设置 | 说明 |
|---|---|
| 工具仓库根目录 | **最常需要填的一项**，含 `config/` 与 `styles/` 的目录 |
| inloop 可执行文件 | 一般不必填——有仓库根就够了。探测不到时可手填完整路径 |
| 内容目录 | 默认 `<vault>/InLoopPub`，即文章存放位置 |
| 预览宽度 | 模拟手机阅读宽度，默认 430px |
| 实时预览延迟 | 停止输入多久后重新渲染，默认 400ms |

**路径错配是这类工具最常见的故障**，表现为"看不到我的文章"或"找不到 inloop"。
设置界面每栏下方都会显示**当前实际使用的值**，出问题时先看那里。

## 使用

| 操作 | 位置 |
|---|---|
| 打开面板 | 左侧丝带图标，或命令面板「InLoop 手记：打开 InLoop 面板」 |
| 新建推文 | 面板顶部「新建推文」，或命令面板 |
| 实时预览 | 打开内容目录里的 `index.md`，右侧预览会随输入更新（有防抖） |
| 切换状态 | 每篇文章右侧的下拉（想法 / 调研中 / 草稿 / 待审 / 可发布 / 已发布） |
| 构建并复制 | 面板顶部按钮，或命令面板 |
| 删除 | 文章行右侧的垃圾桶图标（会二次确认并显示图片数量） |

### 发布到公众号

**半自动（默认，无需任何凭据）**

1. 点「构建并复制」→ 正文 HTML（含样式）进剪贴板
2. 打开公众号后台 → 新建图文 → **在正文区粘贴**（不要用源码模式）
3. **按面板里的图片清单逐张上传正文图片**——微信编辑器不抓本地路径，
   这一步只能人工做，面板会告诉你第几张图在哪一节内
4. 填标题、作者、摘要，上传封面
5. 手机预览一次再发布

> 「构建并复制」写入的是 **`text/html`** flavor，不是纯文本。微信靠它取得内联样式——
> 只有纯文本的话粘过去会丢掉全部排版。如果环境拿不到 Electron 的原生剪贴板，
> 插件会**明确提示样式未写入**，而不是静默降级。

**全自动（需要公众号凭据 + 固定 IP）**

```bash
inloop publish-wechat <slug>      # 上传图片、回填正文、创建草稿
inloop publish-status             # 看凭据配好没有
```

它做三件事：上传正文图片换取微信 URL、把正文里的本地路径替换掉、创建草稿。
**不群发**——草稿建好后仍由你在后台预览确认。

两条前提（缺一不可）：

1. 公众号的 AppID 与 AppSecret
2. **本机出口 IP 已加入公众号后台的 IP 白名单**

凭据二选一：

```bash
# 环境变量
export INLOOP_WECHAT_APPID=wx...
export INLOOP_WECHAT_SECRET=...

# 或文件（不入 Git）
config/wechat.credentials.json   →   {"appid": "wx...", "secret": "..."}
```

> ⚠️ **这一层在本机从未成功执行过**：没有凭据，且家宽 IP 不稳定无法加白名单。
> 接口路径与参数取自公开文档，首次使用时请核对
> `src/inloop/publishers/wechat_api.py` 顶部的 `_API_*` 常量。
> 家庭宽带通常需要一台固定 IP 的机器做出口。

## 开发

```bash
npm run dev        # esbuild watch，改代码即重建
npm run typecheck  # tsc --noEmit
npm run smoke      # 冒烟测试：真的调用 Python 内核跑 list/check/build
npm run unit       # 纯函数单测：预览与剪贴板逻辑
npm run check      # typecheck + build + smoke + unit
```

产物只有两个文件：`dist/main.js` 与 `dist/manifest.json`。
样式通过注入 `<style>` 提供（`src/styles.ts`），因此不必额外部署 `styles.css`。

### 代码结构

```text
src/
├── main.ts           插件类：生命周期、命令、事件、构建并复制
├── view.ts           面板与预览视图
├── preview-utils.ts  纯函数：iframe 包裹、取 body、去标签（不依赖 Obsidian，可单测）
├── settings.ts       设置界面与路径探测
├── styles.ts         面板样式（注入 <style>）
├── obsidian-env.ts   宿主环境辅助（vault 路径、系统打开、剪贴板多 flavor）
└── inloop/
    └── cli.ts        调用 Python 内核并解析 JSON
```

`preview-utils.ts` 单独存在是有原因的：上一轮有两个缺陷（预览图片全坏、
复制丢排版）都埋在 `ItemView` 里，而当时的测试一条都覆盖不到。
抽成不依赖 Obsidian 的纯函数后，`npm run unit` 就能守住它们。

### 测试覆盖的边界

| 测试 | 覆盖 | 不覆盖 |
|---|---|---|
| `npm run unit` | iframe 的 base 与 sandbox、取 body、去标签 | 真实 iframe 渲染 |
| `npm run smoke` | 调用内核、JSON 契约、错误码映射 | Obsidian 界面 |
| **手工验证** | 插件加载、预览流畅度、剪贴板能否写入、微信端呈现 | — |

**最后一行只有人能做**，不要因为前两行通过就认为整个插件可用。

## 已知限制

- **仅桌面版**（`isDesktopOnly: true`）：需要调用外部进程，移动版做不到
- **需要 Python**：见上文"代价"
- **预览有成本**：Python 启动约 300ms + 构建 250–350ms，叠加 400ms 防抖后，
  停止输入到看到预览约 0.9–1.0 秒。**长文章不是瓶颈**（成本被进程启动主导）
- **自动发布未验证**：见上文"全自动"一节的警告
- 微信端最终呈现无法自动验证：粘贴后的效果只能在编辑器里看
