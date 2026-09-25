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

<!-- 索引由 `inloop index` 自动生成，请勿手工编辑本区块 -->

待生成：`inloop index`（任务书 §14）尚未实现。

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

> **当前状态**：仓库处于第一阶段早期。可用命令只有 `inloop version`、`inloop info`、
> `inloop root`；`new` / `check` / `build-wechat` / `preview-wechat` / `index`
> 尚未实现，会在对应模块完成后逐条接入。构建与发布流程见 `docs/publishing-guide.md`。
>
> 底层已可用：front matter 解析与文章模型（`inloop.parser.frontmatter`、
> `inloop.models.article`）已实现，包含字段校验与规则码，但尚未接入命令行。

## 免责声明

本仓库内容为个人学习与研究记录，不代表任何机构立场。文中涉及的论文解读、
源码分析与实验结论均为个人理解，可能存在错误；据此做出的技术决策请自行验证。
引用的论文、代码与图片版权归原作者所有。

## License

待定（`TBD`）。
