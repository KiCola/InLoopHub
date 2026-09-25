<!--
  主题清单：每个主题的定位、适用场景与调参入口。

  这是给人看的说明，不是构建的输入（构建只读 themes/*.css）。
  新增主题时在下面补一条，并说明"它和别的主题差在哪"——
  否则半年后自己也说不清为什么要有这个主题。

  共用部分（颜色、字体、图片、表格、卡片配色）在 styles/base.css，不要在这里重复。
-->

# 主题清单

| 主题 | 风格定位 | 适用场景 |
|---|---|---|
| `inloop` | **默认**。标题带主色下划线，二级标题浅底框，卡片圆角 + 主色左竖线。节奏偏紧凑（15px / 1.75 / 24px） | 技术内容：论文拆解、源码分析、实验日志 |
| `compact` | 与默认同源但更素：卡片方角 + 左竖线，无二级标题底框 | 需要更"文档感"、少装饰的场合 |
| `standard` | 居中标题 + 上下细线，卡片圆角无竖线，节奏中等（16px / 1.85 / 28px） | 偏叙述的长文、研究随想 |
| `generous` | 主色底块标题，正文两端对齐，节奏最松（16px / 1.95 / 36px） | 需要强视觉锚点、以观点为主的稿件 |

## 主题之间到底差在哪

三个维度，改主题基本就是在这三个维度上取值：

| 维度 | 取值区间 | 影响 |
|---|---|---|
| 节奏 | 行高 1.75 → 1.95，段间距 24 → 36px | 同样字数下页面长度；越松越"杂志"，越紧越"文档" |
| 标题形式 | 下划线 / 居中细线 / 主色底块 / 浅色底框 | 章节的视觉权重，最容易看出主题差异的地方 |
| 卡片形式 | 圆角有无、竖线有无、内距大小 | 与正文的区分度 |

## 调参入口

所有可调项都在 `themes/<名称>.css` 里，**改数值不需要动代码**：

| 想改什么 | 改哪个选择器 |
|---|---|
| 正文字号、行高、字距 | `.inloop-article` |
| 段间距 | `.inloop-article p` 的 `margin` |
| 各级标题形式 | `.inloop-article h1` … `h4` |
| 卡片外形 | `.inloop-article blockquote` 与 `blockquote blockquote` |
| 列表、表格、代码块间距 | 对应的 `ul` / `table` / `pre` |
| 图注 | `.inloop-article .inloop-caption` |

颜色不要在这里写死，用 `base.css` 里的变量：`var(--brand-primary)`、
`var(--brand-primary-soft)`、`var(--brand-quote-bg)`、`var(--brand-dark-bg)` 等。

## 新建主题的步骤

1. 复制一个最接近的现有主题：`cp themes/standard.css themes/我的主题.css`
2. 只改节奏与外形，颜色继续用变量
3. `inloop themes` 确认被识别
4. `python scripts/utils/make_theme_preview.py` 生成对照页，与现有主题并排比对
5. 定稿后把 `config/wechat.yaml` 的 `theme` 指向它，并在本文件补一条说明

## 一条容易踩的坑

给通用 `blockquote` 写 `background` 会与深底卡片规则**同特异性竞争**，
表现为"写了深底却渲染成浅底"。这两种形态用的是互斥选择器
（`blockquote` 与 `blockquote blockquote`），改的时候不要破坏这个结构。

另外：`background` 简写会重置浏览器的 `border-left-color`。
若要在深底卡片上单独改竖线颜色，必须写完整的 `border-left: 3px solid <色>`。
