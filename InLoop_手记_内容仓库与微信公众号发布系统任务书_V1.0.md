# InLoop 手记内容仓库与微信公众号发布系统任务书 V1.0

> **修订记录**
>
> 本文档在开发过程中按实际决定修订，保持"当前事实描述"的唯一性——
> 不保留"已废弃条款 + 批注"的双份信息。
>
> | 日期 | 修订内容 | 原因 |
> |---|---|---|
> | 2026-09-25 | §1、§2、§3：内容源由"GitHub 仓库"改为"内容目录"；项目结构改为"工具仓库 + 独立内容目录"两段式 | 作者决定把文章放在自己的 Obsidian 仓库（坚果云同步、不纳入 Git），工具单独开源 |
> | 2026-09-25 | §23：取消 GitHub Actions | 作者决定不引入 CI；本地 `ruff` + `pytest` + `inloop check` 已足够 |
> | 2026-09-25 | §25：P1 第 15 项标注为已取消 | 同上 |
> | 2026-09-25 | §27、§28：示例路径与文章编号更新为实际值；示例文章定位由"第一批真实文章"改为"排版回归样本" | 内容已迁出工具仓库；原编号中的 004/005 已删除 |
> | 2026-09-25 | §29：交付物清单同步取消 Actions | 同上 |

## 1. 项目名称

**InLoop Notes Publishing System**

目标：构建一个**内容源与工具解耦**的个人技术内容管理与发布系统。

**内容源是一份"内容目录"，不是某个特定仓库。** 它可以位于任意位置——本机任意路径、
Obsidian 仓库内、坚果云等同步目录，或者一个独立的 Git 仓库。工具本身单独开源，
不要求用户把文章放进工具仓库。

第一阶段仅支持：

> **Markdown → 微信公众号文章**

后续预留：

> 个人博客 / 知乎 / 小红书 / Bilibili

---

## 2. 核心设计原则

系统必须遵循以下原则：

- **内容目录是唯一事实源**（不限定它是不是 Git 仓库）
- 所有文章以 Markdown 存储
- 一篇文章对应一个独立目录
- 图片与文章就近管理
- 公众号发布第一阶段采用“半自动”
- 先生成兼容微信公众号的 HTML
- 暂不直接自动群发
- 所有脚本必须支持 CLI
- 配置项集中管理
- 所有平台适配层与内容源解耦
- 后续新增平台时，不修改文章正文结构

核心目标不是“全自动发公众号”，而是：

> **让文章内容、素材、状态、构建、发布流程长期可维护。**

---

## 3. 推荐仓库结构

系统由**两个互不耦合的部分**组成：工具仓库（开源、可升级、可替换）与内容目录（作者的长期资产）。

### 3.1 工具仓库

```text
inloop-notes/                    # 工具本身，开源
├── README.md
├── LICENSE
├── .gitignore
├── pyproject.toml
├── config/
│   ├── site.yaml                # 含 content.root：指向内容目录
│   └── wechat.yaml
│
├── examples/                    # 排版回归样本（非作者的真实文章）
│   └── 2026/
│       ├── 001-hello-inloop/
│       │   ├── index.md
│       │   ├── cover.png
│       │   └── assets/
│       └── 002-light-o1/
│           ├── index.md
│           ├── cover.png
│           └── assets/
│
├── templates/
│   ├── article.md
│   ├── paper-note.md
│   ├── build-log.md
│   ├── research-note.md
│   └── diary.md
│
├── assets/                      # 仓库级共享素材
│   ├── brand/
│   ├── covers/
│   └── common/
│
├── scripts/
│   ├── new_article.py
│   ├── check_article.py
│   ├── build_wechat.py
│   ├── generate_index.py
│   └── utils/
│
├── styles/                      # 样式事实源，构建时内联
│   ├── base.css
│   ├── code.css
│   └── themes/
│
├── dist/                        # 构建产物，可随时删除重建（不入 Git）
│   ├── wechat/
│   └── metadata/
│
└── docs/
    ├── architecture.md
    ├── content-workflow.md
    ├── publishing-guide.md
    ├── style-guide.md
    └── roadmap.md
```

### 3.2 内容目录

内容目录的路径由 `content_root` 决定，**可以位于任意位置**：

```text
<content_root>/                  # 例如 Obsidian 仓库内的某个文件夹
├── INDEX.md                     # 文章总览，由 `inloop index` 维护
└── 2026/
    ├── 001-hello-inloop/
    │   ├── index.md
    │   ├── cover.png
    │   └── assets/
    └── 002-light-o1/
        ├── index.md
        ├── cover.png
        └── assets/
```

### 3.3 content_root 的解析顺序

| 优先级 | 来源 | 用途 |
|---|---|---|
| 1 | `--content <路径>` 命令行参数 | 插件/脚本按当前上下文传入 |
| 2 | `INLOOP_CONTENT` 环境变量 | 本机固定配置，免去每次传参 |
| 3 | `config/site.yaml` 的 `content.root` | 开源用户的默认配置 |
| 4 | `<工具仓库>/articles` | 兜底，保证未配置时仍可运行 |

**为什么要解耦**：文章是长期资产，工具是可替换的。绑在一起会导致升级工具要动内容、
别人想用工具得先 fork 文章、文章历史里混着工具代码的提交噪音。

---

## 4. Markdown 文章规范

每篇文章统一使用 YAML Front Matter。

示例：

```yaml
---
id: 002
title: "Light-O1：20Hz Humanoid Foundation Model 到底意味着什么？"
slug: "light-o1"
date: 2026-09-25
author: "YOUR_NAME"
category: "paper"
status: "draft"

tags:
  - Humanoid
  - Robot Learning
  - Foundation Model

summary: "拆解 Light-O1 的核心架构、20Hz 控制机制与实际意义。"

cover: "cover.png"

platforms:
  wechat: true
  blog: false
  zhihu: false
  xiaohongshu: false
  bilibili: false
---
```

必须支持至少以下字段：

```text
id
title
slug
date
author
category
status
tags
summary
cover
platforms
```

其中 `status` 支持：

```text
idea
researching
draft
review
ready
published
```

---

## 5. 文章正文格式约定

正文使用标准 Markdown。

支持：

```text
标题
段落
引用
粗体
斜体
有序/无序列表
表格
图片
GIF
代码块
公式
超链接
分割线
脚注
```

图片建议统一：

```markdown
![Architecture](assets/architecture.png)
```

不要依赖绝对路径。

---

## 6. 模板设计

必须提供至少 5 种模板。

### 6.1 通用文章

`templates/article.md`

结构：

```markdown
# 标题

> TL;DR

## 01 背景

## 02 正文

## 03 分析

## 04 我的理解

## 05 参考资料
```

### 6.2 Paper Note

`templates/paper-note.md`

结构：

```text
TL;DR
Problem
Motivation
Method
Architecture
Experiment
Interesting Points
Limitations
My Thoughts
References
```

### 6.3 Build Log

`templates/build-log.md`

结构：

```text
Goal
Setup
Baseline
What I Tried
Failed Attempts
Debugging
Result
Lessons Learned
Next Step
```

### 6.4 Research Note

结构：

```text
Problem
Hypothesis
Related Work
Idea
Possible Architecture
Experiments
Risks
Open Questions
```

### 6.5 Diary

偏个人内容，不做过强模板限制。

---

## 7. CLI 工具需求

建议提供统一入口：

```bash
python -m inloop <command>
```

或：

```bash
inloop <command>
```

最低需要实现以下命令。

### 7.1 新建文章

```bash
inloop new
```

交互式询问：

```text
title
category
year
template
slug
```

自动生成：

```text
2026/003-example/
├── index.md
├── assets/
└── cover.png placeholder
```

自动分配文章 ID。

支持：

```bash
inloop new --template build-log
```

### 7.2 检查文章

```bash
inloop check 002-light-o1
```

检查：

- front matter 是否完整
- slug 是否合法
- 日期格式
- 图片是否存在
- cover 是否存在
- 图片是否有 alt
- 本地引用是否失效
- 是否存在绝对路径
- status 是否合法
- tags 是否为空
- summary 是否为空
- Markdown 语法异常

输出：

```text
PASS
WARNING
ERROR
```

---

## 8. 微信公众号构建工具

核心命令：

```bash
inloop build-wechat 002-light-o1
```

输入：

```text
index.md
assets/
cover.png
```

输出：

```text
dist/wechat/002-light-o1/
├── article.html
├── article.preview.html
├── metadata.json
├── images/
└── cover.png
```

---

## 9. 微信 HTML 转换要求

### 9.1 基础转换

支持：

```text
h1-h4
p
blockquote
ul
ol
table
code
pre
img
a
hr
```

### 9.2 微信兼容样式

不得依赖：

```text
JavaScript
外部 CSS
复杂 CSS selector
iframe
```

最终 HTML 应尽可能使用：

```text
inline style
```

例如：

```html
<p style="font-size:16px; line-height:1.8;">
```

### 9.3 设计风格

参考目标：

> 简洁、克制、技术感、适合移动端阅读

整体建议：

```text
正文宽松
标题明显
颜色克制
代码清晰
引用简洁
少用彩色背景块
```

品牌主色：

> **Klein Blue / 克莱茵蓝**

建议统一配置：

```yaml
brand:
  primary: "#002FA7"
  text: "#22252B"
  secondary_text: "#6B7280"
  background: "#FFFFFF"
```

允许对克莱茵蓝做少量渐变扩展。

---

## 10. 微信文章样式规范

### 一级标题

建议：

```text
01
为什么这个问题值得研究
```

或：

```text
01 · Problem
```

不要使用过度花哨图标。

### 二级标题

适度缩进或加左侧短线。

### 正文

建议：

```text
font-size: 16px
line-height: 1.75-1.9
```

段间距明显。

### 引用

左侧蓝色竖线：

```text
Klein Blue
```

背景可使用极浅蓝灰。

### 代码块

深色背景或浅灰背景均可。

需要：

```text
monospace
overflow-x
适配手机
```

### 图片

要求：

```text
max-width: 100%
居中
上下留白
```

可自动生成 caption。

---

## 11. 图片处理

构建时：

1. 扫描文章本地图片
2. 复制到：

```text
dist/wechat/<slug>/images/
```

3. 校验格式
4. 推荐自动压缩
5. 推荐生成 WebP 版本，但微信 HTML 默认优先兼容 PNG/JPEG
6. 大图给出 WARNING

建议阈值：

```text
> 3MB warning
> 8MB error
```

GIF 单独处理。

---

## 12. metadata.json

构建后生成：

```json
{
  "title": "...",
  "summary": "...",
  "author": "...",
  "date": "...",
  "cover": "...",
  "source": "...",
  "status": "ready",
  "platform": "wechat"
}
```

后续微信公众号 API 自动化时直接复用。

---

## 13. HTML 预览模式

生成：

```text
article.preview.html
```

模拟手机阅读宽度：

```text
375px - 430px
```

用于本地浏览器预览。

建议提供：

```bash
inloop preview-wechat 002-light-o1
```

启动本地 HTTP server，例如：

```text
http://localhost:8000
```

---

## 14. 内容索引

实现：

```bash
inloop index
```

自动扫描（`<content_root>` 由 §3.3 的规则解析）：

```text
<content_root>/**
```

生成：

```text
<content_root>/INDEX.md 中的文章索引区块
```

**为什么是 `INDEX.md` 而不是工具仓库的 README**（2026-09-25 修订）：
索引描述的是**内容**，内容迁出工具仓库后，索引也应跟随内容——
作者打开自己的内容目录就能看到文章总览；工具仓库的 README 不再列举作者的文章。

程序只替换标记 `<!-- inloop:index:begin -->` 与 `<!-- inloop:index:end -->`
之间的区块，文件其余部分属于作者，程序不得改动。

内容包括：

```text
ID
标题
日期
分类
状态
Tags
```

---

## 15. README 设计

README 至少包括：

```text
InLoop 手记介绍
Logo
项目目的
文章索引
栏目说明
如何阅读源码文章
如何本地构建微信公众号 HTML
免责声明
License
```

推荐定位文案：

> InLoop 手记是一个记录具身智能、机器人学习、实验过程与科研思考的长期个人技术内容仓库。

---

## 16. 公众号内容栏目

代码层面支持以下 category：

```text
paper
code
build
research
diary
```

对应内容：

| Category | 中文 |
|---|---|
| paper | 论文拆解 |
| code | 源码深挖 |
| build | 实验日志 |
| research | 研究随想 |
| diary | 科研生活 |

---

## 17. 内容工作流

推荐：

```text
idea
 ↓
researching
 ↓
draft
 ↓
review
 ↓
ready
 ↓
published
```

系统允许：

```bash
inloop status <article> ready
```

修改 front matter。

---

## 18. 微信发布 V1 策略

V1 **禁止直接自动群发**。

流程：

```text
Markdown
↓
build-wechat
↓
preview
↓
check
↓
复制 HTML
↓
微信公众号后台
↓
逐张上传正文图片          ← 见下方「实测结论」
↓
填标题 / 作者 / 摘要，上传封面
↓
人工预览
↓
人工发布
```

原因：

> 保留最终人工审核环节，避免格式、图片、封面和链接异常。

### 实测结论（2026-09-25，在真实文章上验证）

| 项 | 结论 |
|---|---|
| 本地相对路径图片经粘贴 | **不会**自动上传。编辑器读不到本机文件，该位置为空 |
| 外链图片（如 GitHub raw） | **不抓取**。粘贴后只显示成一串 URL 文字 |
| 微信官方素材接口 | 需要 AppID/AppSecret，且**必须在后台把发起请求的 IP 加入白名单** |
| 样式是否保留 | **保留良好**：标题底框、卡片、代码着色、图注、表格均正常 |
| 代码块空白 | 已修复（此前会丢缩进与词间空格，导致示例代码不可运行） |

**推论**：

1. **正文图片只能在编辑器里逐张手动上传**，这是 V1 的硬约束，
   因此构建产物必须提供**图片顺序清单**（哪张图在哪一节内），降低人工成本。
2. 微信编辑器**不是 Markdown 渲染器**，不解析 `**加粗**`、`![图](网址)` 等语法；
   发布指南必须写明这一点。
3. 将来若要自动化图片环节，前置条件是：拿到 AppID/AppSecret，
   并且有一台 **IP 固定**的机器发起上传请求。

---

## 19. 微信发布 V2 预留接口

代码架构需要预留：

```text
publishers/
├── base.py
├── wechat.py
├── blog.py
├── zhihu.py
├── xiaohongshu.py
└── bilibili.py
```

定义统一抽象接口：

```python
class Publisher:
    def build(self, article):
        ...

    def publish(self, article):
        ...

    def update(self, article):
        ...
```

V1 只实现：

```text
WechatBuilder
```

无需实现真实 publish。

---

## 20. 配置文件

`config/site.yaml`

```yaml
site:
  name: "InLoop 手记"
  author: "YOUR_NAME"

brand:
  primary: "#002FA7"
  text: "#22252B"
  secondary_text: "#6B7280"
  background: "#FFFFFF"
```

`config/wechat.yaml`

```yaml
wechat:
  font_size: 16
  line_height: 1.8
  heading_style: "numbered"
  inline_css: true
  image_max_width: 100
```

---

## 21. 技术栈建议

优先 Python。

推荐：

```text
Python >= 3.11
PyYAML
markdown-it-py
mdit-py-plugins
BeautifulSoup4
Jinja2
Pillow
Typer
Rich
```

可选：

```text
Pygments
watchdog
pytest
ruff
black
```

CLI 推荐：

> Typer + Rich

---

## 22. 测试要求

至少提供：

```text
tests/
├── test_frontmatter.py
├── test_markdown.py
├── test_images.py
├── test_wechat_builder.py
└── fixtures/
```

重点测试：

- front matter 解析
- 图片路径
- Markdown → HTML
- inline CSS
- 代码块
- 表格
- 中文标题
- Unicode
- GIF
- 不存在图片
- 空字段

---

## 23. GitHub Actions

**本节已取消（2026-09-25）。**

原计划实现基础 CI（`push / PR → ruff → pytest → article validation`）。
作者决定不引入，理由：

- 内容已迁出工具仓库，CI 无法覆盖作者的真实文章
- 本地检查已足够：`ruff check .`、`pytest`、`inloop check --all`
- 为个人项目维护 CI 配置与 runner 环境不划算

**将来若重新需要**（例如接受外部贡献），本节内容可直接复用：
`ruff` → `pytest` → 文章校验，文章有 ERROR 则 fail，只有 WARNING 则 pass 并报告。

---

## 24. Git 工作流

推荐分支：

```text
main
draft/*
feature/*
```

文章编辑可直接：

```text
draft/light-o1
```

完成后合入 main。

未来可把：

> merge main

视作“文章内容已经稳定”。

---

## 25. 第一阶段开发优先级

### P0

必须完成：

1. 仓库初始化
2. Markdown 规范
3. Front Matter parser
4. Article model
5. `new`
6. `check`
7. Markdown → HTML
8. 微信 inline CSS
9. 图片处理
10. preview HTML

### P1

完成：

11. README index
12. metadata.json
13. 模板系统
14. Rich CLI
15. ~~GitHub Actions~~ **已取消**（见 §23）
16. pytest

### P2

以后做：

17. 微信 API
18. 自动上传图片
19. 自动创建微信公众号草稿
20. 博客生成
21. 小红书卡片
22. B站脚本生成
23. 知乎适配

---

## 26. 第一阶段禁止过度工程化

不要：

- Docker 优先
- 数据库
- Web 后台
- React/Vue 管理页面
- 用户系统
- OAuth
- 消息队列
- 微服务
- Redis
- Kubernetes

第一阶段就是：

> **Git + Markdown + Python CLI**

越简单越好。

---

## 27. 验收标准

完成后，我应该能执行（`<content_root>` 由 §3.3 的规则解析）：

```bash
git clone ...
cd inloop-notes

pip install -e .

inloop new --template paper-note

inloop check 001-example

inloop build-wechat 001-example

inloop preview-wechat 001-example
```

并获得：

```text
✓ Markdown 校验通过
✓ 图片校验通过
✓ 微信 HTML 构建完成
✓ Preview 已生成
```

最终：

```text
dist/wechat/<slug>/article.html
```

复制至微信公众号后台后，要求：

- 标题层级正常
- 图片正常（**注意：图片需在编辑器中逐张手动上传，详见 §18**）
- 代码正常
- 表格可读
- 引用正常
- 手机阅读体验良好
- 不依赖外部 CSS
- 不依赖 JS

---

## 28. 第一批真实文章

开发时不要全部用 lorem ipsum，需要准备覆盖各种写法的真实中文技术文章。

**定位变更（2026-09-25）**：这批文章原先既是"作者的第一批真实文章"，
也是"排版回归样本"。内容迁出工具仓库后，它们**归入 `examples/`，只作为排版回归样本**——
作者的真实文章位于 `content_root`，不属于工具仓库。

当前实际的示例文章：

```text
examples/2026/
├── 001-hello-inloop      开篇，含代码块与外链
├── 002-light-o1          论文拆解，含公式降级、表格、深浅卡片
└── 003-robodojo          实验日志，含多行代码块、表格、图片
```

（原编号中的 `004-g1-reaching`、`005-practice-run` 已由作者删除。）

至少用一篇真实中文技术文章测试：

- 中文
- 英文缩写
- 代码
- 图片
- 表格
- 引用
- 外链
- GIF

否则很容易出现“测试页面很好看，真正技术文章一塌糊涂”。

**作者自己的文章如何校验**：示例文章只能覆盖已知写法。作者的真实文章位于
`content_root`，需要用 `inloop check --all` 主动校验——
工具测试跑的是 `examples/`，覆盖不到作者的实际内容。

---

## 29. 最终交付物

编程 AI 最终必须交付：

```text
完整 Git 仓库
README
CLI
模板
示例文章（位于 examples/，见 §28）
测试
Wechat CSS
构建后的示例 HTML
开发文档
```

**GitHub Actions 已取消**（见 §23），不再属于交付物。

并在：

```text
docs/architecture.md
```

解释：

```text
Article Model
Parser
Renderer
Wechat Adapter
Asset Pipeline
Future Publisher Interface
```

---

## 30. 给编程 AI 的核心要求

> 请把该项目实现为一个“内容即代码 Content-as-Code”的个人技术内容仓库。GitHub Markdown 是唯一事实源，微信公众号只是第一个渲染目标。第一阶段追求简单、可靠、可维护，不追求全自动发布。重点做好 Markdown 规范、文章元数据、资产管理、微信公众号兼容 HTML 渲染和本地预览，同时保证未来能够无痛扩展到个人博客、知乎、小红书和 Bilibili。

---

## 31. 开发执行建议

第一轮只完成 **P0**。

不要一次性实现全部功能。

推荐开发顺序：

```text
仓库初始化
↓
Article Model
↓
Front Matter Parser
↓
new
↓
check
↓
Markdown Renderer
↓
Wechat Style
↓
Asset Pipeline
↓
Preview
```

在完成第一篇真实文章后，根据实际使用体验再决定：

- 是否修改目录结构
- 是否增加模板
- 是否调整样式系统
- 是否接入微信公众号 API
- 是否扩展到博客和其他平台

核心原则：

> **先让系统真的可用，再让系统变得完整。**
