"""微信 HTML 渲染：CSS 内联 + 白名单清洗。

这是样式唯一的施加点（docs/architecture.md 第 3 节）。设计要点：

1. **样式来自 ``styles/wechat.css``，不在代码里硬编码。** 该文件同时是设计依据的
   文字出处；这里负责把它解析成「选择器 → 声明」并解析 CSS 变量。
2. **只使用元素/后代选择器匹配。** 微信编辑器会丢弃 ``class``，也不认
   ``#id``、``:hover``、媒体查询等。遇到无法用内联表达的选择器时，
   **明确报错而不是静默跳过**——静默跳过意味着样式悄悄丢失。
3. **产物零 class。** ``class`` 在粘贴后可能丢失，且是编辑器样式重写的突破口。
4. **可选语法着色。** Pygments 可用时给代码块着色，不可用时降级为无高亮的 ``pre``，
   不报错（AGENTS.md §5）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup, Tag

from inloop.config import Config

#: 正文容器标签（粘贴范围）
ARTICLE_TAG = "div"

#: 正文容器在样式表中的选择器。产物中容器不带 class，该规则只用于取容器自身样式。
CONTAINER_SELECTOR = ".inloop-article"

#: 图片说明使用的标记 class 名。产物中会被去掉，仅用于生成阶段查询样式。
CAPTION_MARKER = "inloop-caption"

#: 纯结构容器：它们本身不承载样式，样式落在子元素上。
#: 这些标签未匹配到样式属于正常，不应计入「样式可能漏了」的提示。
STRUCTURAL_CONTAINERS: frozenset[str] = frozenset(
    {"br", "hr", "tr", "thead", "tbody", "html", "body"}
)


class StyleError(ValueError):
    """样式表无法解析或包含无法内联的写法。"""


class StyleSheet:
    """已解析的样式表：选择器 → 声明。

    Attributes:
        rules: ``(normalized_selector, declarations)`` 列表，保持文件中的顺序，
            以便后出现的规则可以覆盖先出现的。规范化后的选择器用于**元素匹配**。
        raw_rules: ``(原始选择器, declarations)`` 列表。容器规则（``.inloop-article``）
            在规范化后会变成空字符串，无法再用于匹配，因此必须保留原始写法。
        variables: ``:root`` 中定义的 CSS 变量。
    """

    def __init__(
        self,
        rules: list[tuple[str, dict[str, str]]],
        variables: dict[str, str],
        raw_rules: list[tuple[str, dict[str, str]]] | None = None,
    ) -> None:
        self.rules = rules
        self.raw_rules = raw_rules if raw_rules is not None else list(rules)
        self.variables = variables

    def declarations_for(self, tag: Tag) -> dict[str, str]:
        """按元素匹配所有规则，返回合并后的声明。

        匹配规则：选择器最后一段决定目标标签（如 ``blockquote p`` → ``p``），
        前面的部分用祖先关系校验。这一点足以表达本项目用到的全部选择器，
        又避免了实现一个完整的 CSS 引擎。
        """
        merged: dict[str, str] = {}
        for selector, declarations in self.rules:
            if _matches(tag, selector):
                merged.update(declarations)
        return merged

    def container_declarations(self) -> dict[str, str]:
        """取正文容器自身的声明。

        容器规则在 CSS 中写作 ``.inloop-article``，规范化后会变成空字符串
        （容器类名不参与元素匹配），因此必须按**原始选择器**查找。
        产物中容器标签不带 class，所以这些声明只能直接写到容器的 ``style`` 上——
        否则正文的基础字号、行高、颜色与字体族会全部丢失。
        """
        merged: dict[str, str] = {}
        for selector, declarations in self.raw_rules:
            if selector.strip() == CONTAINER_SELECTOR:
                merged.update(declarations)
        return merged

    def declarations_for_class(self, tag_name: str, class_name: str) -> dict[str, str]:
        """按「标签名 + 一个 class」查询声明。

        仅用于**生成阶段**：构建脚本需要按 class 选择器（如 ``.inloop-caption``）
        取到样式，然后把样式直接写到元素上。产物中不保留任何 class，
        因此这里查到的声明必须内联，不能依赖选择器在产物中继续生效。
        """
        merged: dict[str, str] = {}
        needle = f".{class_name}"
        for selector, declarations in self.rules:
            parts = selector.split()
            if not parts:
                continue
            last = parts[-1]
            if needle not in last:
                continue
            # 末段形如 `.inloop-caption` 或 `p.inloop-caption`
            base = last.replace(needle, "").strip()
            if base and base != tag_name:
                continue
            merged.update(declarations)
        return merged


def load_stylesheet(config: Config) -> StyleSheet:
    """读取并解析样式表。

    依次读取 ``styles/wechat.css`` 与 ``styles/code.css``，后者用于语法着色，
    仅在 Pygments 可用时生效。
    """
    styles_dir = config.root / "styles"
    parts: list[str] = []
    for name in ("wechat.css", "code.css"):
        path = styles_dir / name
        if not path.is_file():
            raise StyleError(
                f"缺少样式文件：{path}\n"
                f"修正方法：确认 styles/ 目录下存在 {name}；该文件是样式的唯一事实源，"
                f"代码中不硬编码颜色与字号。"
            )
        parts.append(path.read_text(encoding="utf-8"))

    return parse_css("\n".join(parts))


def parse_css(text: str) -> StyleSheet:
    """解析 CSS 文本。

    Raises:
        StyleError: 选择器含无法内联的写法。
    """
    # 去掉注释，避免其中的花括号干扰解析
    cleaned = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)

    variables: dict[str, str] = {}
    rules: list[tuple[str, dict[str, str]]] = []
    raw_rules: list[tuple[str, dict[str, str]]] = []

    for selector_block, body in re.findall(r"([^{}]+)\{([^{}]*)\}", cleaned):
        selectors = [s.strip() for s in selector_block.split(",") if s.strip()]
        declarations: dict[str, str] = {}
        for item in body.split(";"):
            if ":" not in item:
                continue
            name, _, value = item.partition(":")
            # 折叠值中的空白：CSS 允许声明跨行书写，
            # 但产物是内联样式，保留换行与缩进只会让 HTML 变脏。
            normalized_value = re.sub(r"\s+", " ", value).strip()
            declarations[name.strip()] = normalized_value
        if not declarations:
            continue

        # 收集 CSS 变量，稍后统一替换为字面值
        if any(selector == ":root" for selector in selectors):
            variables.update(declarations)
            continue

        for selector in selectors:
            _validate_selector(selector)
            # 两份都留：规范化后的用于元素匹配，原始的用于识别容器规则
            # （`.inloop-article` 规范化后为空字符串，无法再被识别）
            rules.append((normalize_selector(selector), declarations))
            raw_rules.append((selector, declarations))

    def resolve(items: list[tuple[str, dict[str, str]]]) -> list[tuple[str, dict[str, str]]]:
        return [
            (selector, {k: _resolve_value(v, variables) for k, v in decls.items()})
            for selector, decls in items
        ]

    return StyleSheet(
        rules=resolve(rules), variables=variables, raw_rules=resolve(raw_rules)
    )


#: 微信端无法内联、出现即报错的写法
_UNSUPPORTED_SELECTOR_HINTS = (
    ":hover",
    ":focus",
    ":active",
    "::",
    "@media",
    "@supports",
)


def _validate_selector(selector: str) -> None:
    """检查选择器是否能可靠地内联到元素上。"""
    lowered = selector.lower()
    for hint in _UNSUPPORTED_SELECTOR_HINTS:
        if hint in lowered:
            raise StyleError(
                f"样式选择器无法内联到元素上：`{selector}`（含 `{hint}`）。\n"
                f"修正方法：微信正文只支持 inline style，请改用元素或后代选择器，"
                f"或把该样式直接写成目标元素上的属性。"
            )
    if "#" in selector:
        raise StyleError(
            f"样式选择器含 id：`{selector}`。产物不保留 id，该样式不会生效。\n"
            f"修正方法：改用元素选择器。"
        )


def normalize_selector(selector: str) -> str:
    """去掉容器前缀，把 ``.inloop-article p`` 规范成 ``p``。

    容器类名只是"粘贴范围"的标记，不是样式挂载点：产物零 class，
    因此匹配时应忽略它。
    """
    parts = selector.split()
    return " ".join(part for part in parts if not part.startswith(".inloop-article"))


def _matches(tag: Tag, selector: str) -> bool:
    """判断元素是否匹配选择器。

    支持本项目用到的形式：``tag``、``tag tag``（后代）、``tag > tag``（子代）。
    """
    if not selector:
        return False

    chain = selector.replace(">", " > ").split()
    return _match_chain(tag, chain)


def _match_chain(tag: Tag, chain: list[str]) -> bool:
    if not chain:
        return True

    token = chain[-1]
    if token == ">":
        # 形如 [..., ">", "parent"]：当前是 parent 的子元素
        if len(chain) < 2:
            return False
        parent_token = chain[0]
        parent = tag.parent
        return (
            isinstance(parent, Tag)
            and _tag_matches(parent, parent_token)
            and _match_chain(parent, chain[:-2])
        )

    if not _tag_matches(tag, token):
        return False

    remaining = chain[:-1]
    if not remaining:
        return True

    ancestor = tag.parent
    while isinstance(ancestor, Tag):
        if _match_chain(ancestor, remaining):
            return True
        ancestor = ancestor.parent
    return False


def _tag_matches(tag: Tag, token: str) -> bool:
    if token == "*":
        return True
    return tag.name == token


def _resolve_value(value: str, variables: dict[str, str]) -> str:
    """把 ``var(--x)`` 替换为字面值。

    微信编辑器不保证保留 CSS 变量，且 inline style 中变量引用在部分客户端不解析，
    因此产物里必须是具体值。
    """

    def replace(match: re.Match[str]) -> str:
        name = match.group(1).strip()
        return variables.get(name, match.group(0))

    previous = value
    for _ in range(5):  # 变量可能互相引用，迭代到稳定
        current = re.sub(r"var\(\s*(--[\w-]+)\s*(?:,[^)]*)?\)", replace, previous)
        if current == previous:
            break
        previous = current
    return previous


# --- 渲染 -----------------------------------------------------------------


@dataclass(slots=True)
class WechatRenderResult:
    """渲染结果。

    Attributes:
        html: 带内联样式的正文 HTML（含容器标签）。
        unstyled_tags: 未匹配到任何样式的标签名，供排查"样式漏了"。
        warnings: 渲染提示。
    """

    html: str
    unstyled_tags: tuple[str, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())


def render_wechat_html(
    body_html: str,
    *,
    config: Config,
    stylesheet: StyleSheet | None = None,
    container: bool = True,
) -> WechatRenderResult:
    """把规范化后的 HTML 渲染为微信兼容 HTML。

    Args:
        body_html: 正文 HTML 片段。
        config: 配置（提供字号、代码主题等）。
        stylesheet: 已解析的样式表；为 None 时自动加载。
        container: 是否套上正文容器标签。产物需要，预览外壳不需要。

    Returns:
        渲染结果。
    """
    sheet = stylesheet or load_stylesheet(config)
    soup = BeautifulSoup(body_html, "html.parser")

    _apply_code_highlighting(soup)
    _build_figures(soup, config, sheet)

    warnings: list[str] = []
    unstyled: dict[str, None] = {}

    for tag in soup.find_all(True):
        declarations = sheet.declarations_for(tag)
        existing_style = tag.get("style")
        has_inline_style = isinstance(existing_style, str) and existing_style.strip() != ""

        if not declarations:
            # 元素已经带样式（例如语法着色生成的 token span）时不算"漏样式"：
            # 这些样式来自 Pygments，不由样式表提供。
            if not has_inline_style and tag.name not in STRUCTURAL_CONTAINERS:
                unstyled.setdefault(tag.name, None)
            continue

        tag["style"] = merge_styles(existing_style if has_inline_style else None, declarations)

    _force_wechat_safe_attributes(soup)

    body = soup.body
    inner = "".join(str(child) for child in body.children) if body else str(soup)

    if not container:
        return WechatRenderResult(
            html=inner, unstyled_tags=tuple(unstyled), warnings=tuple(warnings)
        )

    # 容器样式直接查规则表得到，不构造临时标签：
    # 在同一个 soup 上既取子节点又挂新容器，追加时会清空取到的内容。
    container_style = sheet.container_declarations()
    if container_style:
        style_attr = to_style_attribute(container_style)
        return WechatRenderResult(
            html=f'<{ARTICLE_TAG} style="{style_attr}">{inner}</{ARTICLE_TAG}>',
            unstyled_tags=tuple(unstyled),
            warnings=tuple(warnings),
        )
    return WechatRenderResult(
        html=f"<{ARTICLE_TAG}>{inner}</{ARTICLE_TAG}>",
        unstyled_tags=tuple(unstyled),
        warnings=tuple(warnings),
    )


def merge_styles(existing: str | None, declarations: dict[str, str]) -> str:
    """合并已有 style 与新的声明；新声明覆盖同名属性。"""
    merged: dict[str, str] = {}
    if existing:
        for item in existing.split(";"):
            if ":" in item:
                name, _, value = item.partition(":")
                merged[name.strip()] = value.strip()
    merged.update(declarations)
    return to_style_attribute(merged)


def to_style_attribute(declarations: dict[str, str]) -> str:
    """把声明字典写成 ``style`` 属性值，保持稳定顺序。"""
    return "".join(f"{name}:{value};" for name, value in declarations.items())


def _force_wechat_safe_attributes(soup: BeautifulSoup) -> None:
    """补齐微信端必需、而又容易丢失的属性，并去掉全部 class。"""
    for image in soup.find_all("img"):
        existing = image.get("style", "")
        image["style"] = merge_styles(
            existing if isinstance(existing, str) else None,
            {"max-width": "100%", "height": "auto"},
        )
    for link in soup.find_all("a"):
        existing = link.get("style", "")
        link["style"] = merge_styles(
            existing if isinstance(existing, str) else None, {"word-wrap": "break-word"}
        )

    # 产物必须零 class：class 在粘贴后可能丢失，也会成为编辑器样式重写的突破口。
    # 到这一步样式已全部内联，class 不再有用途，统一清除。
    for tag in soup.find_all(True):
        if tag.has_attr("class"):
            del tag["class"]


def _build_figures(soup: BeautifulSoup, config: Config, sheet: StyleSheet) -> None:
    """按图片的 alt/title 生成图片说明。

    任务书 §10 要求「可自动生成 caption」。这里优先用 ``title``，
    没有 title 时退回 ``alt``；两者都为空则不生成。

    图注样式按 ``.inloop-caption`` 规则查出后**直接内联**——产物零 class，
    若指望选择器在产物中生效，图注会悄悄变成普通段落。
    """
    caption_style = sheet.declarations_for_class("p", CAPTION_MARKER)
    for image in soup.find_all("img"):
        caption_text = image.get("title") or image.get("alt")
        if not isinstance(caption_text, str) or not caption_text.strip():
            continue
        # title 已用于生成说明文字，从元素上移除以免浏览器再弹一个浮层提示
        if image.has_attr("title"):
            del image["title"]

        caption = soup.new_tag("p")
        if caption_style:
            caption["style"] = to_style_attribute(caption_style)
        caption.string = caption_text.strip()

        # 图片通常被包在 <p> 里；把说明插到该段落之后，避免嵌套 <p>
        parent = image.parent
        if isinstance(parent, Tag) and parent.name == "p":
            parent.insert_after(caption)
        else:
            image.insert_after(caption)


#: 代码块语言 → Pygments lexer 名（仅列常用项，其余交给 Pygments 猜测）
def _apply_code_highlighting(soup: BeautifulSoup) -> None:
    """给代码块加语法着色。

    Pygments 不可用时什么也不做：产物依旧是可读的等宽代码块。
    """
    blocks = soup.find_all("pre")
    if not blocks:
        return
    try:
        from pygments import highlight
        from pygments.formatters import HtmlFormatter
        from pygments.lexers import TextLexer, get_lexer_by_name
        from pygments.util import ClassNotFound
    except ImportError:  # pragma: no cover - Pygments 是可选依赖
        return

    for block in blocks:
        code = block.find("code")
        if code is None:
            continue
        text = code.get_text()
        language = _detect_language(code)

        lexer = TextLexer()
        if language:
            try:
                lexer = get_lexer_by_name(language)
            except ClassNotFound:
                lexer = TextLexer()

        formatter = HtmlFormatter(nowrap=True)
        highlighted = highlight(text, lexer, formatter)
        token_styles = _token_style_map(formatter)

        fragment = BeautifulSoup(highlighted, "html.parser")
        # Pygments 会为没有任何样式的 token（标点、空白）也生成 <span>。
        # 它们保留下来只会让 HTML 变长，并制造"未匹配样式"的噪音告警，
        # 因此先记下样式，再把空 span 解开。
        plain_spans: list[Tag] = []
        for span in fragment.find_all("span"):
            classes = span.get("class") or []
            declarations: dict[str, str] = {}
            for name in classes:
                declarations.update(token_styles.get(name, {}))
            if declarations:
                span["style"] = to_style_attribute(declarations)
            else:
                plain_spans.append(span)
            # class 一律去掉：产物零 class
            if span.has_attr("class"):
                del span["class"]

        for span in plain_spans:
            span.unwrap()

        code.clear()
        for child in list(fragment.children):
            code.append(child)


def _detect_language(code: Tag) -> str:
    """从 ``<code class="language-python">`` 中取出语言名。"""
    classes = code.get("class") or []
    for name in classes:
        if isinstance(name, str) and name.startswith("language-"):
            return name[len("language-") :]
    return ""


def _token_style_map(formatter: object) -> dict[str, dict[str, str]]:
    """把 Pygments 的样式表解析成 token class → 声明。"""
    from pygments.formatters import HtmlFormatter

    assert isinstance(formatter, HtmlFormatter)
    css = formatter.get_style_defs()
    try:
        sheet = parse_css(css)
    except StyleError:
        # 语法着色样式解析失败不应影响正文构建
        return {}

    mapping: dict[str, dict[str, str]] = {}
    for selector, declarations in sheet.rules:
        # Pygments 生成的形如 `.highlight .k`、`.k`；取最后一段作为 token 类名
        parts = selector.split()
        if not parts:
            continue
        token = parts[-1].lstrip(".")
        if token:
            mapping.setdefault(token, {}).update(declarations)
    return mapping
