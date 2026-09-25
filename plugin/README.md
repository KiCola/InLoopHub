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

设置界面里三项，**留空则自动探测**，每项下方会显示当前实际用的值：

| 设置 | 默认行为 |
|---|---|
| inloop 可执行文件 | 自动找 `<工具仓库>/.venv/Scripts/inloop.exe` |
| 工具仓库根目录 | 从可执行文件位置反推（`/.venv/` 之前的部分） |
| 内容目录 | 默认 `<vault>/InLoopPub` |

**第一次使用请先确认「内容目录」**——路径错配是这类工具最常见的故障，
表现为"看不到我的文章"。插件在读取失败时会提示去哪里检查。

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
