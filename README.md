# InLoop 手记

> 记录具身智能、机器人学习、实验过程与科研思考的长期个人技术内容仓库。

## 这是什么

一个**内容即代码（Content-as-Code）**的个人技术内容仓库：

- **GitHub 仓库是唯一内容源。** 文章以 Markdown 存储，图片与文章就近管理。
- **微信公众号是第一个渲染目标**，不是终点。后续预留博客、知乎、小红书、Bilibili。
- **平台适配层与内容源彻底解耦。** 新增平台不修改文章正文结构。

核心目标不是"全自动发公众号"，而是：**让文章内容、素材、状态、构建、发布流程长期可维护。**

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

## 文章索引

<!-- inloop:index:begin -->

共 4 篇。

| ID | 日期 | 栏目 | 标题 | 状态 | 标签 |
|---|---|---|---|---|---|
| 001 | 2026-09-20 | 科研生活 | [开篇：为什么我要把技术内容做成一个仓库](articles/2026/001-hello-inloop/index.md) | published | 内容管理、写作、工作流 |
| 002 | 2026-09-25 | 论文拆解 | [Light-O1：20Hz 人形基础模型到底意味着什么](articles/2026/002-light-o1/index.md) | review | Humanoid、Robot Learning、Foundation Model |
| 003 | 2026-09-23 | 实验日志 | [RoboDojo 复现记录：从数据集到可训练策略](articles/2026/003-robodojo/index.md) | review | 复现、数据集、模仿学习 |
| 004 | 2026-09-24 | 源码深挖 | [G1 抓取任务复盘：一次失败的策略与三条可用的经验](articles/2026/004-g1-reaching/index.md) | draft | 抓取、Sim2Real、调试 |

<!-- inloop:index:end -->

## 栏目

| Category | 中文 | 内容 |
|---|---|---|
| `paper` | 论文拆解 | 论文的问题、方法、实验与我的判断 |
| `code` | 源码深挖 | 读源码的过程与结论 |
| `build` | 实验日志 | 复现、搭建、调试的真实过程，含失败 |
| `research` | 研究随想 | 方向性思考与开放问题 |
| `diary` | 科研生活 | 偏个人的记录 |

## 如何阅读源码文章

源码类文章写的是**过程**，不是结论。文中的代码片段来自当时的真实环境，
可能因为依赖版本变化而需要调整。遇到跑不通的地方，优先对照文章日期与依赖版本。

## 如何本地构建

```bash
git clone https://github.com/KiCola/InLoopHub.git
cd InLoopHub

# 建议使用虚拟环境
python -m venv .venv
# Windows: .venv\Scripts\activate    Linux/macOS: source .venv/bin/activate

pip install -e ".[dev]"
inloop --help
```

## 常用命令

> **第一次使用？** 看 [docs/getting-started.md](docs/getting-started.md)，
> 那是从新建文章到粘贴进公众号的完整走查。

| 命令 | 作用 |
|---|---|
| `inloop new --title "标题" --slug your-slug --template paper-note` | 新建文章 |
| `inloop new --list` | 查看可用模板 |
| `inloop check articles/2026/002-light-o1` | 校验一篇文章（Front Matter、图片、正文） |
| `inloop build-wechat articles/2026/002-light-o1` | 生成微信公众号产物 |
| `inloop build-wechat <文章> --theme generous` | 指定排版主题构建 |
| `inloop themes` | 列出可用排版主题 |
| `inloop preview-wechat 002-light-o1` | 构建并启动本地手机宽度预览 |
| `inloop index` | 重新生成本文索引 |
| `inloop status <article> ready` | 修改文章状态 |
| `inloop rules` | 列出全部校验规则码 |

`<文章>` 可写目录、`index.md` 路径或 slug（推荐 slug，最短）。
`check` 的退出码：无问题为 `0`，存在 ERROR 为 `1`——可直接用于 CI。

构建产物在 `dist/wechat/<slug>/` 下：`article.html` 是要复制进公众号后台的正文，
`article.preview.html` 是本地预览页，`metadata.json` 是发布元数据。

## 本地开发

```bash
python -m pytest          # 运行测试
python -m ruff check .    # 静态检查
```

测试会直接对 `articles/` 下的**真实文章**跑完整构建，而不是只用简单样例——
这样才能发现"简单样例很好看、真正技术文章一塌糊涂"的问题。

## 免责声明

本仓库内容为个人学习与研究记录，不代表任何机构立场。文中涉及的论文解读、
源码分析与实验结论均为个人理解，可能存在错误；据此做出的技术决策请自行验证。
引用的论文、代码与图片版权归原作者所有。

## License

待定（`TBD`）。
