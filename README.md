# InLoop 手记

> 记录具身智能、机器人学习、实验过程与科研思考的长期个人技术内容仓库。

**目录**：[这是什么](#这是什么) · [安装](#安装) · [怎么用](#怎么用) ·
[文章索引](#文章索引) · [栏目](#栏目) · [排版主题](#排版主题) ·
[目录导航](#目录导航) · [本地开发](#本地开发)

## 这是什么

一个**内容即代码（Content-as-Code）**的个人技术内容仓库：

- **GitHub 仓库是唯一内容源。** 文章以 Markdown 存储，图片与文章就近管理。
- **微信公众号是第一个渲染目标**，不是终点。后续预留博客、知乎、小红书、Bilibili。
- **平台适配层与内容源彻底解耦。** 新增平台不修改文章正文结构。

核心目标不是"全自动发公众号"，而是：**让文章内容、素材、状态、构建、发布流程长期可维护。**

## 安装

```bash
git clone https://github.com/KiCola/InLoopHub.git
cd InLoopHub

# 建议使用虚拟环境
python -m venv .venv
pip install -e ".[dev]"
inloop --help
```

### 激活虚拟环境

不同 shell 的写法**不一样**，写错会表现为 `inloop: command not found`：

| Shell | 命令 |
|---|---|
| Windows CMD | `.venv\Scripts\activate.bat` |
| Windows PowerShell | `.venv\Scripts\Activate.ps1` |
| **Git Bash / MSYS2 / WSL** | `source .venv/Scripts/activate`（**必须带 `source`**） |
| Linux / macOS | `source .venv/bin/activate` |

Git Bash 用户的三个常见坑：

1. **漏掉 `source`。** 直接运行 `.venv/Scripts/activate` 是在子进程里执行，
   退出后 PATH 恢复原样，`inloop` 依旧找不到。
2. **用反斜杠。** bash 把 `\` 当转义符，`.venv\Scripts\inloop.exe` 会变成
   `.venvScriptsinloop.exe`。bash 里一律用 `/`。
3. **路径写成 `E:\InLoopHub`。** 在 bash 里应写 `/e/InLoopHub`。

**最省事的办法：不激活，直接用完整路径。** 这对任何 shell 都成立：

```bash
.venv/Scripts/inloop.exe check 005-practice-run     # Git Bash / CMD（显式 .exe）
.venv/Scripts/inloop check 005-practice-run         # Git Bash 会自动补 .exe
.venv/bin/inloop check 005-practice-run             # Linux / macOS
```

验证激活是否生效：

```bash
echo $PATH | tr ':' '\n' | grep -i inloophub        # 有输出即为已激活
```

### 已经 `source` 了但还是找不到命令？

多半是 PATH 被写成了 Windows 形式（`E:\...\.venv\Scripts`），bash 认不出来。
本仓库提供一个辅助脚本，按当前平台的习惯重新设置并明确报告结果：

```bash
source scripts/activate.sh
```

它只做"设 PATH + 报告状态"，不改变任何项目行为。

## 怎么用

### 1. 新建文章

```bash
inloop new --title "文章的完整标题" --slug your-slug --template paper-note
```

- `--slug`：英文短名，只用小写字母、数字与连字符。它决定目录名，
  **发布后不要再改**（改了等于新建一篇）。
- `--template`：见下方模板表，不确定就先 `inloop new --list` 看说明。
- 文章编号自动分配，不用管。
- 不带参数运行 `inloop new` 会逐项询问。

生成结果：

```text
articles/2026/005-your-slug/
├── index.md      ← 你要写的文件，只有它
├── cover.png     ← 自动生成的占位封面，发布前建议换掉
└── assets/       ← 文章配图放这里
```

| 模板 | 适用 | 栏目 |
|---|---|---|
| `paper-note` | 论文拆解 | `paper` |
| `build-log` | 实验日志、复现过程 | `build` |
| `research-note` | 研究随想、假设与想法 | `research` |
| `diary` | 科研生活、随笔 | `diary` |
| `article` | 通用，不确定时选它 | 自定义 |

### 2. 写内容

用任何能编辑纯文本的工具都行：VS Code、Typora、Obsidian 都可以。
**只编辑 `index.md`**，它由两部分组成，上面那段 YAML 是元数据，不要删：

```markdown
---
id: 5                  # 自动分配，别改
title: "文章的完整标题"
slug: your-slug        # 与目录名对应，别改
date: 2026-09-25
author: Zero Zhao
category: research     # 栏目，取值见「栏目」一节
status: draft          # 状态，见第 5 步
tags:                  # 标签，至少写一个
  - 标签一
summary: "一句话摘要"   # 发布时要用，别空着
cover: cover.png
platforms:
  wechat: true         # 至少发到公众号
---

# 正文大标题          ← 从这里开始写正文
```

正文用标准 Markdown，没有私有语法：

```markdown
## 01 · 章节标题

普通段落。可以**加粗**、*斜体*、`行内代码`、[外链](https://example.com)。

> **我最想让读者记住的一句话**      ← 主色加粗文字，无卡片

> 我自己写的一句补充说明            ← 浅底卡片

> > 引述别人的话（推文、公告）       ← 深底卡片

![图片说明](assets/图.png "图注")

| 列A | 列B |
|---|---|
| 1 | 2 |

- 无序列表
1. 有序列表
```

**一条重要规矩：不要手工调排版。** 不要用空格缩进或用多余空行去对齐——
排版完全由主题决定，手工排版在换主题后必然错位。

标题里的编号（`01`）靠手写，构建不会自动补号。同一层级要么都写，要么都不写。

更细的写作规范（术语、图片规格、三种引用形态的判定标准）见
[docs/style-guide.md](docs/style-guide.md)。

### 3. 放图片

1. 把图片文件拷进**该文章的** `assets/` 目录
   （如 `articles/2026/005-your-slug/assets/architecture.png`）
2. 正文用**相对路径**引用：`![架构图](assets/architecture.png)`

三条硬规矩：

- **不要用绝对路径**（`C:\...`、`/Users/...`），检查会直接报错。
- **不要用图床外链**当主要图片——图片要和文章一起进 Git，否则将来链接会失效。
- **单张别超过 3MB**（超过给警告，8MB 以上报错）。

`cover.png` 是文章目录下的封面，发布前建议换成真封面（比例 2.35:1 为佳）。

### 4. 随时检查

```bash
inloop check 005-your-slug
```

输出分三级：`✓ 通过`、`WARNING`（可继续但建议改）、`ERROR`（必须改，构建会中断）。
查某个规则码的含义用 `inloop rules`。

### 5. 改状态

状态按流程推进：`idea` → `researching` → `draft` → `review` → `ready` → `published`

```bash
inloop status 005-your-slug ready
```

这条命令只改 front matter 里的 `status` 一行，不动正文；也可以直接手改 `index.md`。

### 6. 本地预览

```bash
inloop preview-wechat 005-your-slug
```

会自动打开浏览器，看到**手机宽度**（430px）下的真实观感。`Ctrl+C` 停止。

- 只构建不预览：`inloop build-wechat 005-your-slug`
- 换端口：加 `--port 9000`；不想自动开浏览器：加 `--no-open`

### 7. 发到公众号

产物在 `dist/wechat/005-your-slug/`：

| 文件 | 用途 |
|---|---|
| `article.html` | **要复制进公众号的正文** |
| `article.preview.html` | 本地预览页，**不要**用它发布 |
| `metadata.json` | 元数据、渲染选项，以及图片结构化清单 |
| `images/` | 正文图片实体文件 |
| `cover.png` | 封面 |

手动步骤：

1. 用浏览器打开 `article.html`
2. **全选 → 复制**（`Ctrl+A`、`Ctrl+C`）
3. 公众号后台 → 新建图文 → 在正文区**粘贴**（可视区粘贴，不要切"源码模式"）
4. **按构建时打印的发布清单，逐张上传正文图片**
5. 在后台单独填**标题**、**作者**、**摘要**（这些不从 HTML 里取）
6. 上传封面图
7. **在手机上预览一次** → 人工发布

> ⚠️ **图片只能在编辑器里手动上传。** 已实测确认：微信编辑器既不读本地文件路径，
> 也不抓取外链图片，粘贴进去的位置是空的。`build-wechat` 结束时会打印
> 「发布清单」，写明第几张图在哪一节内，照着顺序传即可。
>
> ⚠️ **微信编辑器不是 Markdown 编辑器**，它不解析 `**加粗**`、`![图](网址)` 这类语法。
> 要加粗用编辑器工具栏，图片用工具栏上传。

### 8. 保存与提交

```bash
git add .
git commit -m "post: 新增文章《标题》"
git push
```

### 命令一览

| 命令 | 作用 |
|---|---|
| `inloop new --list` | 查看可用模板 |
| `inloop new --title "..." --slug x --template paper-note` | 新建文章 |
| `inloop check <文章>` | 校验一篇文章 |
| `inloop build-wechat <文章>` | 生成公众号产物 |
| `inloop build-wechat <文章> --theme generous` | 指定排版主题构建 |
| `inloop preview-wechat <文章>` | 本地手机宽度预览 |
| `inloop index` | 更新 README 里的文章索引 |
| `inloop status <文章> ready` | 修改文章状态 |
| `inloop themes` | 查看可用排版主题 |
| `inloop rules` | 查看校验规则码含义 |
| `inloop info` | 查看当前生效的配置 |

`<文章>` 可写目录、`index.md` 路径或 slug（推荐 slug，最短）。
`check` 的退出码：无问题为 `0`，存在 ERROR 为 `1`——可直接用于 CI。

### 遇到问题

| 现象 | 原因与解决 |
|---|---|
| `inloop` 不是内部或外部命令 | 虚拟环境没激活，或没执行 `pip install -e .` |
| 找不到文章 | slug 打错了，用 `inloop info` 看已有文章列表 |
| 构建报 ERROR | 按提示改；`inloop rules` 查规则码含义 |
| 图片报 `IMG001` | 正文里的路径与实际文件位置不一致 |
| 预览页图片不显示 | 图片没放进 `assets/`，或路径写错 |
| 粘贴后样式丢了 | 确认复制的是 `article.html`，且是可视区粘贴而非源码模式 |

## 文章索引

<!-- inloop:index:begin -->

共 4 篇。

| ID | 日期 | 栏目 | 标题 | 状态 | 标签 |
|---|---|---|---|---|---|
| 001 | 2026-09-20 | 科研生活 | [开篇：为什么我要把技术内容做成一个仓库](articles/2026/001-hello-inloop/index.md) | published | 内容管理、写作、工作流 |
| 002 | 2026-09-25 | 论文拆解 | [Light-O1：20Hz 人形基础模型到底意味着什么](articles/2026/002-light-o1/index.md) | review | Humanoid、Robot Learning、Foundation Model |
| 003 | 2026-09-23 | 实验日志 | [RoboDojo 复现记录：从数据集到可训练策略](articles/2026/003-robodojo/index.md) | review | 复现、数据集、模仿学习 |
| 006 | 2026-09-25 | 研究随想 | [Try](articles/2026/006-try/index.md) | published | try |

<!-- inloop:index:end -->

## 栏目

| Category | 中文 | 内容 |
|---|---|---|
| `paper` | 论文拆解 | 论文的问题、方法、实验与我的判断 |
| `code` | 源码深挖 | 读源码的过程与结论 |
| `build` | 实验日志 | 复现、搭建、调试的真实过程，含失败 |
| `research` | 研究随想 | 方向性思考与开放问题 |
| `diary` | 科研生活 | 偏个人的记录 |

## 排版主题

排版节奏由主题决定，可随时切换，**换主题不影响文章正文**：

```bash
inloop themes                                   # 看全部主题及定位
inloop build-wechat <文章> --theme generous     # 临时指定
```

永久切换改 `config/wechat.yaml` 的 `wechat.theme`。默认主题是 `inloop`
（标题带主色下划线、二级标题浅底框、卡片圆角 + 主色左竖线、节奏偏紧凑）。

每次构建都会把当次生效的选项写进 `metadata.json` 的 `render_options` 与
产物的 `<meta name="inloop:theme">`，因此旧文章"当时长什么样"可查、可复现。
主题的定位、调参入口与新建步骤见 [styles/themes/README.md](styles/themes/README.md)。

## 目录导航

| 目录 | 作用 |
|---|---|
| `articles/` | 文章正文，唯一内容源 |
| `drafts/` | 未成文的草稿与想法 |
| `templates/` | 文章模板 |
| `assets/` | 仓库级共享素材（Logo、通用封面等） |
| `config/` | 配置：站点信息与微信渲染参数 |
| `styles/` | 样式事实源（构建时内联，产物不外链 CSS） |
| `src/inloop/` | Python 包，全部逻辑所在 |
| `scripts/` | CLI 入口薄封装，不承载逻辑 |
| `tests/` | 自动化测试 |
| `docs/` | 开发文档 |
| `dist/` | 构建产物，可随时删除重建 |

每个目录下都有 `README.md` 说明用途与存放规则。

## 如何阅读源码文章

源码类文章写的是**过程**，不是结论。文中的代码片段来自当时的真实环境，
可能因为依赖版本变化而需要调整。遇到跑不通的地方，优先对照文章日期与依赖版本。

## 本地开发

```bash
python -m pytest          # 运行测试
python -m ruff check .    # 静态检查
```

测试会直接对 `articles/` 下的**真实文章**跑完整构建，而不是只用简单样例——
这样才能发现"简单样例很好看、真正技术文章一塌糊涂"的问题。

架构说明（Article Model、Parser、Renderer、微信适配、素材流水线、发布接口）
见 [docs/architecture.md](docs/architecture.md)。

## 免责声明

本仓库内容为个人学习与研究记录，不代表任何机构立场。文中涉及的论文解读、
源码分析与实验结论均为个人理解，可能存在错误；据此做出的技术决策请自行验证。
引用的论文、代码与图片版权归原作者所有。

## License

本仓库采用 [MIT License](LICENSE)。

- **代码**（`src/`、`scripts/`、`tests/`、配置与脚本）可自由使用、修改、再分发，
  只需保留版权声明。
- **文章正文与配图**：原创内容版权归作者所有，**转载或引用请注明出处**
  （本仓库地址，或公众号「InLoop 手记」）。文章中出现的外部图表、论文截图等
  版权归原作者，转载前请自行确认授权。
