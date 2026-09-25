# 架构说明

本文解释系统的六个核心构件及其边界。需求来源是任务书，本文只讲**怎么实现、为什么这样实现**。
对应任务书 §29 要求解释的六项：Article Model、Parser、Renderer、Wechat Adapter、
Asset Pipeline、Future Publisher Interface。

## 0. 一句话结构

```text
<content_root>/**/index.md            ← 唯一内容源（默认 content/，不入库）
        │
        │  parse        （纯函数，不做校验）
        ▼
   (meta, body)  ──validate──▶  Article     ← 数据模型
        │
        │  render
        ▼
   HTML 片段  ──inline + whitelist──▶  微信兼容 HTML
        │                                   │
        │  assets                           │  write
        ▼                                   ▼
   ImageRef 清单 ─────────────────▶  dist/wechat/<slug>/
                                            │
                                            │  publish（第一阶段未实现）
                                            ▼
                                      微信公众号
```

数据单向流动：内容源 → 模型 → 渲染 → 产物。**没有任何一步反向写回内容目录。**

## 1. Article Model

**位置**：`src/inloop/models/`

**职责**：承载文章的语义——front matter 字段、`status` 与 `category` 的合法取值、
`slug` 格式、状态流转约束。

**明确不负责**：

- 不读文件。文件读取是调用方的事，模型不关心文章来自磁盘还是内存。
- 不解析 YAML。这是 Parser 的事。
- 不渲染。模型里不应出现 HTML 字符串。

**为什么这样切**：后续要给博客、知乎、小红书适配时，它们读的是同一个 Article，
却有不同的元数据需求。把语义集中在模型里，适配层就只关心"怎么把这个模型表达出去"。

**校验策略**：不遇到第一个错误就抛异常，而是把所有问题收集进 ``Article.issues``，
一次报全。让人反复"改一处、跑一次"是低效的。规则码形如 ``FM001``，稳定可引用。

**已实现**：``Article`` 数据类、``Status`` / ``Category`` 枚举、``Issue`` 规则码、
以及从 front matter 构造模型并累计问题的完整逻辑。

## 2. Parser

**位置**：`src/inloop/parser/frontmatter.py`、`src/inloop/parser/markdown.py`

**职责**：纯函数式的文本转换。

- `frontmatter`：Markdown 文本 → `(meta: dict, body: str)`。**只做切分与 YAML 解析，
  不做语义校验**——"`date` 格式对不对"属于校验层，不属于解析层。
- `markdown`：Markdown 正文 → HTML 片段。**不加样式、不动图片路径**。

**为什么解析与校验分离**：解析失败与内容不合格是两类问题，报错方式、退出码、
给用户的修复建议都不同。混在一起会导致"格式合法但字段缺失"这类情况只能报一句笼统的错。

**一个具体的设计决定**：解析器**不把日期解析成 `date` 对象**。PyYAML 默认会把
`date: 2026-09-25` 构造成 `datetime.date`，于是 `2026-02-30` 这种不存在的日期会在
解析阶段抛底层错误（`day is out of range`），而加引号写同样的值却会走到校验阶段——
同一个错误两种报错方式。因此解析器使用一个关闭了时间戳隐式解析的 `SafeLoader` 子类，
让日期始终以字符串进入模型层，由模型层统一校验。

**已实现**：`parse_front_matter()`，处理 BOM、CRLF、空块、未闭合定界符、
YAML 语法错误、顶层非映射，并返回正文起始行号以便把校验结果定位回源文件。

**未实现**：`markdown.py`（Markdown → HTML）。

**为什么渲染不碰图片路径**：图片的实际落盘位置由 Asset Pipeline 决定，
正文该怎么写由渲染层与发布层约定。让解析阶段去猜路径，是耦合的开始。

## 3. Renderer

**位置**：`src/inloop/renderer/`

**职责**：把 HTML 片段变成目标平台可消费的形态。

1. 按 `styles/wechat.css` 的**元素选择器**逐元素写入 inline style。
2. 按白名单清洗：只保留允许的标签与属性，剔除 `<script>`、事件属性、外链 CSS、`iframe`。
3. 处理标题编号（`01 · Problem` 形式）、引用块、表格、代码块、图片与 caption。

**明确不负责**：复制图片、写产物文件。

**为什么必须内联**：微信公众号编辑器会剥离 `<style>` 与外链 CSS，
inline style 是唯一可靠的样式载体（任务书 §9.2）。这也是"产物可直接喂给发布接口"的前提。

**为什么零 class**：class 在粘贴后可能被丢弃，且是编辑器样式重写的突破口；
样式全部落在元素选择器上，产物中不保留任何 class 依赖。

## 4. Wechat Adapter

**位置**：`src/inloop/publishers/wechat.py`

**职责**：`WechatBuilder` 实现 `Publisher.build()`，编排整个构建流程并写出产物：

```text
dist/wechat/<slug>/
├── article.html           可直接复制进后台的正文
├── article.preview.html   手机宽度（375–430px）预览外壳
├── metadata.json          发布所需元数据
├── images/                正文图片实体文件
└── cover.png              封面
```

`publish()` / `update()` 在平台接口接入前保持**显式失败**，不用假成功的返回值占位。

**为什么产物里图片必须是独立文件**：将来接发布接口时，需要逐张上传图片换取平台地址，
再回填到正文。因此图片清单要结构化输出（`ImageRef`），而不能把图片内联成 data URI
烧进 HTML——那样将来只能反解 HTML 才能拿到图片，等于把路堵死（`AGENTS.md` §11）。

## 5. Asset Pipeline

**位置**：`src/inloop/assets/pipeline.py`

**职责**：

1. 扫描正文引用的本地图片。
2. 校验：文件是否存在、扩展名是否受支持、是否用了绝对路径。
3. 检查体积：超过 `image_warning_bytes` 给 WARNING，超过 `image_error_bytes` 给 ERROR
   （阈值来自 `config/wechat.yaml`，不在代码里硬编码）。
4. 复制到产物目录，产出 `ImageRef` 清单供发布阶段回填。

**明确不负责**：决定正文 HTML 里的 `src` 写法。路径改写由渲染层依据清单统一完成，
避免"复制图片"和"改写 HTML"两处各改一半。

**为什么图片与文章就近管理却又要复制一份**：源文件在 `<文章目录>/assets/` 便于作者维护，
产物目录里的副本保证 `dist/` 可以整体拿走使用，不依赖仓库其他部分。

## 6. Future Publisher Interface

**位置**：`src/inloop/publishers/base.py`

**职责**：定义平台无关的抽象，使新增平台不改动内容源。

```python
class Publisher(ABC):
    def build(self, article) -> BuildResult: ...   # 本地构建，无网络
    def publish(self, article): ...                # 上传发布
    def update(self, article): ...                 # 更新已发布内容
```

三个数据结构是这条路的接口契约：

| 结构 | 作用 |
|---|---|
| `BuildResult` | 产物目录、文件清单、图片清单、元数据、警告 |
| `ImageRef` | 源路径 → 产物路径 → HTML 中的 `src`，供上传后回填 |
| `BuildArtifact` | 单个产物文件及其用途与大小 |

**为什么 `build` 与 `publish` 分开**：第一阶段的半自动流程只用 `build`，
它必须能在无网络、无凭据的环境下完成。把网络与凭据需求隔离在 `publish` 里，
构建的可靠性和可测试性都不受平台影响。

**为什么用 Protocol 而不是直接 import Article**：让适配层不依赖模型的具体实现，
便于测试时传入轻量替身，也避免将来模型演进牵动所有平台实现。

## 附：涉及的安全与健壮性约定

- 只允许 `yaml.safe_load`，禁止 `yaml.load`。
- 构建期不发起网络请求（`preview` 起本地 HTTP 服务除外）。
- 产物写入采用"先写临时文件再改名"，避免中断时留下半截文件。
- 构建不修改任何源文件，这条由 `AGENTS.md` §1 第 4 条兜底。
