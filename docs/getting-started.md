# 上手：从写一篇到发出去

本文是**照着做就能完成**的操作走查，覆盖从新建文章到粘贴进公众号的完整流程。
只讲"怎么做"，不讲"为什么这样设计"——后者见 `architecture.md` 与
`styles/README.md`。

## 0. 一次性准备

```bash
cd E:\InLoopHub

python -m venv .venv
.venv\Scripts\activate
pip install -e ".[dev]"
inloop --help
```

以后每次写作只需要：

```bash
cd E:\InLoopHub
.venv\Scripts\activate
```

> Windows 上一句话激活：`.venv\Scripts\activate`。
> 不用激活也能跑，把命令写成 `.venv\Scripts\inloop.exe <命令>` 即可。

## 1. 新建文章

```bash
inloop new --title "文章的完整标题" --slug your-slug --template research-note
```

- `--slug`：英文短名，只用小写字母、数字与连字符。它决定目录名，
  **发布后不要再改**（改了等于新建一篇）。
- `--template`：见下表。不知道选哪个就先 `inloop new --list` 看说明。
- 编号（`005`）自动分配，不用管。

也可以不带参数，命令行会逐项询问：

```bash
inloop new
```

### 模板怎么选

| 模板 | 适用 | 栏目 |
|---|---|---|
| `paper-note` | 论文拆解 | `paper` |
| `build-log` | 实验日志、复现过程 | `build` |
| `research-note` | 研究随想、假设与想法 | `research` |
| `diary` | 科研生活、随笔 | `diary` |
| `article` | 通用，不确定时选它 | 自定义 |

### 生成结果

```text
articles/2026/005-your-slug/
├── index.md      ← 你要写的文件，就是它
├── cover.png     ← 自动生成的占位封面，发布前换成真封面
└── assets/       ← 文章配图放这里
```

## 2. 写内容

**用什么写**：任何能编辑纯文本的工具都行。VS Code、Typora、Obsidian 都可以。
推荐 VS Code —— 仓库里已经配置好了相关规范，且能实时预览 Markdown。

**编辑哪个文件**：只有 `index.md`。它由两部分组成，**上面那段 YAML 不要删**：

```markdown
---
id: 5                     # 自动分配，别改
title: "文章的完整标题"    # 会显示在公众号标题位置（仍需在后台再填一次）
slug: your-slug           # 与目录名对应，别改
date: 2026-09-25          # 自动填今天
author: Zero Zhao
category: research        # 栏目
status: draft             # 状态，见第 5 节
tags:                     # 标签，至少写一个
  - 标签一
summary: "一句话摘要"      # 发布时要用，别空着
cover: cover.png          # 封面文件名
platforms:
  wechat: true            # 至少要发到公众号
---

# 正文大标题            ← 从这里开始写正文
```

**正文支持的写法**（都是标准 Markdown，没有私有语法）：

```markdown
## 01 · 章节标题          章节用 ##（两个井号）

普通段落。可以**加粗**、*斜体*、`行内代码`、[外链](https://example.com)。

> **我最想让读者记住的一句话**     ← 主色加粗文字，无卡片

> 我自己写的一句补充说明           ← 浅底卡片

> > 引述别人的话（推文、公告）      ← 深底卡片

![图片说明](assets/图.png "图注")  图注可选

- 无序列表
1. 有序列表

| 列A | 列B |
|---|---|
| 1 | 2 |

```python
code here
```
```

写段落的规矩只有一条：**不要手工调排版**。不要用空格缩进、不要加多余空行去对齐——
排版完全由主题决定，手工排版在换主题后必然错位。

详细的写作规范（标题写法、术语、图片规格）见 `style-guide.md`。

## 3. 放图片

1. 把图片文件拷进该文章的 `assets/` 目录
   （例如 `articles/2026/005-your-slug/assets/architecture.png`）
2. 在正文里用**相对路径**引用：`![架构图](assets/architecture.png)`

三条硬规矩：

- **不要用绝对路径**（`C:\...` 或 `/Users/...`），检查会直接报错。
- **不要用图床外链**作为主要图片——图片要和文章一起进 Git，否则将来链接会失效。
- **单张别超过 3MB**（超过会给警告，8MB 以上直接报错）。

封面是文章目录下的 `cover.png`，发布前记得换成真封面（建议比例 2.35:1）。

## 4. 写的过程中随时检查

```bash
inloop check articles/2026/005-your-slug
```

输出分三级：

```text
✓ 通过                   一切正常
WARNING ...              能继续，但建议改
ERROR ...                必须改，否则构建会中断
```

也可以简写，直接用 slug：

```bash
inloop check 005-your-slug
```

想知道某个规则码是什么意思：

```bash
inloop rules
```

## 5. 改状态（可选）

把 `status` 按流程推进：`idea` → `researching` → `draft` → `review` → `ready` → `published`

```bash
inloop status 005-your-slug ready
```

这条命令只改 front matter 里的 `status` 一行，不动正文。也可以直接手改 `index.md`。

## 6. 本地预览

```bash
inloop preview-wechat 005-your-slug
```

会自动打开浏览器，看到**手机宽度**（430px）下的真实观感。按 `Ctrl+C` 停止。

- 只想构建不预览：`inloop build-wechat 005-your-slug`
- 换个端口：`inloop preview-wechat 005-your-slug --port 9000`
- 不想自动开浏览器：加 `--no-open`

## 7. 发到公众号

构建产物在 `dist/wechat/005-your-slug/`：

| 文件 | 用途 |
|---|---|
| `article.html` | **要复制进公众号的正文** |
| `article.preview.html` | 本地预览页，**不要**用它发布 |
| `metadata.json` | 标题、摘要、封面等元数据 |
| `images/` | 正文图片 |
| `cover.png` | 封面 |

手动步骤：

1. 用浏览器打开 `article.html`
2. **全选 → 复制**（`Ctrl+A`、`Ctrl+C`）
3. 公众号后台 → 新建图文 → 在正文区**粘贴**
4. 在后台单独填：**标题**、**作者**、**摘要**（这些不从 HTML 里取）
5. 上传封面图
6. 处理图片：编辑器可能要求重新上传本地图片，逐张确认
7. **在手机上预览一次** → 人工发布

> **重要**：不要用"源码模式"粘贴 HTML 源码，要直接在可视区粘贴。
> 第 6 步是本系统唯一未经实测的环节，第一次做请留意图片是否需要逐张手动上传。

## 8. 保存与提交

```bash
git add .
git commit -m "post: 新增文章《标题》"
git push
```

## 常用命令一览

| 命令 | 作用 |
|---|---|
| `inloop new --list` | 看有哪些模板 |
| `inloop new --title "..." --slug x --template paper-note` | 新建文章 |
| `inloop check <文章>` | 检查一篇文章 |
| `inloop build-wechat <文章>` | 生成公众号产物 |
| `inloop preview-wechat <文章>` | 本地手机宽度预览 |
| `inloop index` | 更新 README 里的文章索引 |
| `inloop status <文章> ready` | 改文章状态 |
| `inloop themes` | 看有哪些排版主题 |
| `inloop rules` | 看校验规则码的含义 |
| `inloop info` | 看当前生效的配置 |

`<文章>` 可以写目录、`index.md` 路径，或直接写 slug（推荐用 slug，最短）。

## 遇到问题

| 现象 | 原因与解决 |
|---|---|
| `inloop` 不是内部或外部命令 | 虚拟环境没激活，或没执行 `pip install -e .` |
| 找不到文章 | slug 打错了，用 `inloop info` 看已有文章列表 |
| 构建报 ERROR | 按提示改；`inloop rules` 查规则码含义 |
| 图片报 IMG001 | 正文里的路径与实际文件位置不一致 |
| 预览页图片不显示 | 图片没放进 `assets/`，或路径写错 |
| 粘贴后样式丢了 | 确认复制的是 `article.html`，且是可视区粘贴而非源码模式 |
