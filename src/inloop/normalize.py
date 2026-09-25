"""HTML 规范化：把 Markdown 渲染结果整理成微信可用的结构。

这一步夹在「渲染」与「加样式」之间，专门处理**语义层面的结构改写**，
不涉及配色与字号（那是 :mod:`inloop.renderer.wechat` 的职责）。

处理三类在微信端必然失效的写法：

1. **脚注**：原始产出是 ``<sup><a href="#fn1">[1]</a></sup>`` 加文末
   ``<section class="footnotes">``。微信正文里锚点跳转不可用，且
   ``id`` / ``class`` 会被编辑器丢弃。这里改为文末「注释」有序列表，
   正文中的引用改成无链接的 ``[1]``。
2. **公式**：原产出是 ``<span class="math inline">`` / ``<div class="math block">``，
   依赖前端渲染。改为 ``<code>`` 内联等宽呈现，保留 LaTeX 原文。
   行内公式另加一点左内距，使其与正文有视觉间隔（属于结构需要，不是装饰）。
3. **图片**：抽出 ``src`` / ``alt`` / ``title``，形成素材清单，
   供后续复制文件与改写路径。这里不动 ``src``，避免"复制文件"与"改写 HTML"
   两处各改一半。

另外统一剥离 ``id`` 与 ``class``：产物要求零 class，而 ``id`` 在粘贴后
既可能丢失也可能与编辑器自身元素冲突。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from bs4 import BeautifulSoup, NavigableString, Tag

#: 正文中引用脚注时使用的上标结构（无 href，微信端不可跳转）。
#: 这里只给"上标 + 尺寸 + 颜色"，颜色少样本就是中性灰，具体配色由微信渲染层覆盖。
_FOOTNOTE_REF_STYLE = "vertical-align:super;font-size:12px;color:#6B7280;"

#: 公式降级为等宽文本时的**结构**样式（内距、等宽、可横向滚动）。
#: 背景与配色归微信渲染层，此处不写，避免同一属性两处定义。
_MATH_INLINE_STYLE = "font-family:Consolas,Menlo,monospace;font-size:14px;padding:1px 5px;"
_MATH_BLOCK_STYLE = (
    "font-family:Consolas,Menlo,monospace;"
    "font-size:13px;"
    "line-height:1.7;"
    "white-space:pre;"
    "overflow-x:auto;"
)

#: 脚注区结构样式
_FOOTNOTE_SECTION_STYLE = "margin-top:32px;padding-top:16px;"
_FOOTNOTE_TITLE_STYLE = "font-size:14px;font-weight:700;"
_FOOTNOTE_LIST_STYLE = "margin:0;padding-left:20px;"
_FOOTNOTE_ITEM_STYLE = "font-size:13px;line-height:1.7;"


@dataclass(frozen=True, slots=True)
class ExtractedImage:
    """从正文中抽出的一张图片。

    Attributes:
        src: 原始 ``src`` 值，即正文里写的相对路径。
        alt: 替代文字；缺失时为空字符串。
        title: 可选的图片说明。
        is_local: 是否为本地相对路径（外部图片不参与素材复制）。
    """

    src: str
    alt: str
    title: str
    is_local: bool


@dataclass(frozen=True, slots=True)
class NormalizeResult:
    """规范化结果。

    Attributes:
        html: 规范化后的 HTML 片段。
        images: 正文中出现的图片清单，按出现顺序。
        footnote_count: 降级处理的脚注数量。
        math_count: 降级处理的公式数量（行内与块级合计）。
        warnings: 结构层面的提示。
    """

    html: str
    images: tuple[ExtractedImage, ...] = field(default=())
    footnote_count: int = 0
    math_count: int = 0
    warnings: tuple[str, ...] = field(default=())


def normalize_html(html: str) -> NormalizeResult:
    """规范化 Markdown 渲染出的 HTML 片段。"""
    soup = BeautifulSoup(html, "html.parser")
    warnings: list[str] = []

    footnote_count = _downgrade_footnotes(soup)
    math_count = _downgrade_math(soup)
    images = _extract_images(soup)
    _strip_identifiers(soup)

    if footnote_count:
        warnings.append(
            f"脚注已降级为文末注释列表（{footnote_count} 条）：微信正文不支持锚点跳转。"
        )
    if math_count:
        warnings.append(
            f"公式已降级为等宽文本（{math_count} 处）：微信不支持 MathML 或前端公式渲染。"
        )

    body = soup.body
    result_html = "".join(str(child) for child in body.children) if body else str(soup)
    return NormalizeResult(
        html=result_html,
        images=images,
        footnote_count=footnote_count,
        math_count=math_count,
        warnings=tuple(warnings),
    )


# --- 脚注 -----------------------------------------------------------------


def _downgrade_footnotes(soup: BeautifulSoup) -> int:
    """把锚点式脚注改为文末有序列表。"""
    # 1) 记下每个引用指向的编号，供正文改写使用
    ref_numbers: dict[str, str] = {}
    for ref in soup.select("sup.footnote-ref"):
        link = ref.find("a")
        if link is None:
            continue
        number = link.get_text(strip=True)
        target = link.get("href")
        if isinstance(target, str):
            ref_numbers[target.lstrip("#")] = number
        # 正文中的引用改为无链接上标
        replacement = soup.new_tag("sup")
        replacement["style"] = _FOOTNOTE_REF_STYLE
        replacement.string = number
        ref.replace_with(replacement)

    # 2) 把脚注区改写成有样式说明的列表
    sections = soup.select("section.footnotes")
    count = 0
    for section in sections:
        items: list[Tag] = []
        for index, item in enumerate(section.select("li.footnote-item"), start=1):
            # 去掉返回链接（↩︎ 之类），它在微信端同样不可用
            for backref in item.select("a.footnote-backref"):
                backref.decompose()
            content = item.get_text(" ", strip=True)
            new_item = soup.new_tag("li")
            new_item["style"] = _FOOTNOTE_ITEM_STYLE
            new_item.string = f"[{index}] {content}"
            items.append(new_item)
            count += 1

        if not items:
            section.decompose()
            continue

        replacement_section = soup.new_tag("section")
        replacement_section["style"] = _FOOTNOTE_SECTION_STYLE
        title = soup.new_tag("p")
        title["style"] = _FOOTNOTE_TITLE_STYLE
        title.string = "注释"
        listing = soup.new_tag("ol")
        listing["style"] = _FOOTNOTE_LIST_STYLE
        for item in items:
            listing.append(item)
        replacement_section.append(title)
        replacement_section.append(listing)
        section.replace_with(replacement_section)

    # 3) 分隔线「脚注」样式的小横线没有信息量，去掉
    for separator in soup.select("hr.footnotes-sep"):
        separator.decompose()

    return count


# --- 公式 -----------------------------------------------------------------


def _downgrade_math(soup: BeautifulSoup) -> int:
    """把公式改为等宽文本。"""
    count = 0

    for span in soup.select("span.math.inline"):
        content = span.get_text()
        code = soup.new_tag("code")
        code["style"] = _MATH_INLINE_STYLE
        code.string = content
        span.replace_with(code)
        count += 1

    for div in soup.select("div.math.block"):
        content = div.get_text().strip("\n")
        pre = soup.new_tag("pre")
        pre["style"] = _MATH_BLOCK_STYLE
        code = soup.new_tag("code")
        code["style"] = "font-family:inherit;font-size:inherit;background:transparent;"
        code.string = content
        pre.append(code)
        div.replace_with(pre)
        count += 1

    return count


# --- 图片 -----------------------------------------------------------------

#: 判定为本地图片的写法：不含协议头、不以 / 开头（绝对路径另行报错）
def _is_local_src(src: str) -> bool:
    lowered = src.strip().lower()
    if not lowered:
        return False
    if lowered.startswith(("http://", "https://", "//", "data:", "file://")):
        return False
    return True


def _extract_images(soup: BeautifulSoup) -> tuple[ExtractedImage, ...]:
    """抽取图片信息。

    ``src`` 保持原样：实际路径改写由调用方依据素材清单统一完成，
    避免同一件事在两个地方各做一半。
    """
    images: list[ExtractedImage] = []
    for image in soup.find_all("img"):
        src = image.get("src")
        if not isinstance(src, str) or not src.strip():
            continue
        alt = image.get("alt")
        title = image.get("title")
        images.append(
            ExtractedImage(
                src=src.strip(),
                alt=alt.strip() if isinstance(alt, str) else "",
                title=title.strip() if isinstance(title, str) else "",
                is_local=_is_local_src(src),
            )
        )
    return tuple(images)


# --- 清理 -----------------------------------------------------------------

#: 允许保留的属性白名单。其余属性一律删除。
_ALLOWED_ATTRIBUTES: dict[str, set[str]] = {
    "a": {"href", "title"},
    "img": {"src", "alt", "title"},
    "td": {"colspan", "rowspan"},
    "th": {"colspan", "rowspan"},
}

#: 允许出现在产物中的标签。其余标签会被"解开"（保留文字，去掉标签本身）。
ALLOWED_TAGS: frozenset[str] = frozenset(
    {
        "p", "br", "hr", "span", "strong", "em", "s", "del", "sup", "sub",
        "h1", "h2", "h3", "h4", "h5", "h6",
        "ul", "ol", "li",
        "blockquote", "pre", "code",
        "table", "thead", "tbody", "tr", "th", "td",
        "img", "a", "section",
    }
)

#: 必须整体删除的标签，其内容也不保留。
FORBIDDEN_TAGS: frozenset[str] = frozenset(
    {"script", "style", "iframe", "form", "input", "button", "video", "audio", "canvas", "svg"}
)


def _strip_identifiers(soup: BeautifulSoup) -> None:
    """删除 ``id`` / ``class`` 与不在白名单内的属性。

    ``id`` 与 ``class`` 在微信粘贴后既可能丢失，也可能与编辑器自身结构冲突，
    因此产物中不保留它们。

    ``style`` 被**保留**：规范化阶段写入的是结构样式（缩进、等宽、上标），
    微信渲染层随后会在此基础上叠加配色与字号。两个阶段写入的属性不重叠。
    """
    for tag in soup.find_all(True):
        allowed = _ALLOWED_ATTRIBUTES.get(tag.name, set())
        kept: dict[str, str] = {}
        style = tag.attrs.get("style")
        if isinstance(style, str) and style.strip():
            kept["style"] = style.strip()
        for name, value in tag.attrs.items():
            if name in ("style", "id", "class"):
                continue
            if name in allowed:
                kept[name] = " ".join(value) if isinstance(value, list) else str(value)
        tag.attrs = kept


def sanitize_allowed_tags(soup: BeautifulSoup) -> list[str]:
    """按白名单清洗标签，返回被处理掉的标签名清单。

    危险标签整体删除；其他不在白名单内的标签被"解开"，其文字内容保留——
    丢失内容比留下一个不认识的标签更糟。
    """
    removed: list[str] = []

    for tag in soup.find_all(FORBIDDEN_TAGS):
        removed.append(tag.name)
        tag.decompose()

    for tag in soup.find_all(True):
        if tag.name in ALLOWED_TAGS or tag.name in FORBIDDEN_TAGS:
            continue
        removed.append(tag.name)
        tag.unwrap()

    return removed


def text_of(node: Tag | NavigableString) -> str:
    """取节点纯文本，供需要按文字判断的场景使用。"""
    return node.get_text() if isinstance(node, Tag) else str(node)
