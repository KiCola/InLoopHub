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

from bs4 import BeautifulSoup, NavigableString, Tag

from inloop.config import Config

#: 正文容器标签（粘贴范围）
ARTICLE_TAG = "div"

#: 正文容器在样式表中的选择器。产物中容器不带 class，该规则只用于取容器自身样式。
CONTAINER_SELECTOR = ".inloop-article"

#: 默认主题名
DEFAULT_THEME = "standard"

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


def load_stylesheet(config: Config, theme: str = DEFAULT_THEME) -> StyleSheet:
    """按主题读取并合并样式表。

    合并顺序：``styles/base.css`` → ``styles/code.css`` → ``styles/themes/<主题>.css``。
    后加载的同名属性覆盖先加载的，因此主题文件只管**节奏**（字号、行高、间距、
    标题形式、卡片外形），共用部分只维护一份。

    Args:
        config: 配置，用于定位仓库根。
        theme: 主题名，对应 ``styles/themes/<名称>.css``。

    Raises:
        StyleError: 样式文件缺失，或选择器含无法内联的写法。
    """
    styles_dir = config.root / "styles"
    paths = [
        styles_dir / "base.css",
        styles_dir / "code.css",
        styles_dir / "themes" / f"{theme}.css",
    ]

    parts: list[str] = []
    for path in paths:
        if not path.is_file():
            if path.name == f"{theme}.css":
                available = "、".join(available_themes(config)) or "（无）"
                raise StyleError(
                    f"找不到主题 `{theme}`：{path} 不存在。\n"
                    f"可用主题：{available}。\n"
                    f"修正方法：改用上述之一，或在 styles/themes/ 下新建 `{theme}.css`。"
                )
            raise StyleError(
                f"缺少样式文件：{path}\n"
                f"修正方法：确认 styles/ 目录完整；该文件是样式的唯一事实源，"
                f"代码中不硬编码颜色与字号。"
            )
        parts.append(path.read_text(encoding="utf-8"))

    return parse_css("\n".join(parts))


def available_themes(config: Config) -> tuple[str, ...]:
    """列出可用主题名，按字母序。"""
    themes_dir = config.root / "styles" / "themes"
    if not themes_dir.is_dir():
        return ()
    return tuple(sorted(path.stem for path in themes_dir.glob("*.css")))


def theme_name(config: Config) -> str:
    """取配置中指定的主题名，缺省时用默认主题。"""
    try:
        value = config.wechat_value("theme")
    except Exception:
        return DEFAULT_THEME
    text = str(value).strip()
    return text or DEFAULT_THEME


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

    # 伪类：只允许已实现的那几个。不认识的必须报错——
    # 若静默按"不匹配"处理，样式会悄悄失效，而这类问题极难发现。
    for pseudo in re.findall(r":([a-z-]+)", lowered):
        if pseudo not in _SUPPORTED_PSEUDO:
            supported = "、".join(f":{name}" for name in _SUPPORTED_PSEUDO)
            raise StyleError(
                f"样式选择器使用了未支持的伪类：`:{pseudo}`（来自 `{selector}`）。\n"
                f"修正方法：改用已支持的伪类（{supported}），"
                f"或改用元素/后代选择器表达同样的意图。"
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

    支持本项目用到的形式：

    - ``tag``、``tag tag``（后代）、``tag > tag``（子代）、``tag + tag``（相邻兄弟）
    - ``:only-child``（唯一子元素）
    - ``:has(> tag:only-child)``（直接子元素中有唯一的该标签）

    刻意**不支持** ``:last-child`` / ``:first-child`` 等其余伪类：
    相邻兄弟组合器 ``+`` 已能表达"段间不叠加下边距"这类实际需求，
    而且不依赖伪类。遇到未支持的伪类时**明确报错**，不静默按不匹配处理——
    静默不匹配意味着样式悄悄失效，是最难发现的一类问题。
    """
    if not selector:
        return False

    chain = _tokenize_selector(selector)
    return _match_chain(tag, chain)


def _tokenize_selector(selector: str) -> list[str]:
    """把选择器切成"简单选择器 + 组合器"的序列。

    组合器统一成独立 token（``>`` ``+`` ``~`` 以及表示后代的 ``" "``）：

        ``blockquote p``        → ``[blockquote, " ", p]``
        ``blockquote > p``      → ``[blockquote, ">", p]``
        ``blockquote p + p``    → ``[blockquote, " ", p, "+", p]``

    ``:has(...)`` 内部的括号内容整体属于一个片段，不会在括号内被切开。
    """
    tokens: list[str] = []
    buffer = ""
    depth = 0

    index = 0
    while index < len(selector):
        char = selector[index]
        if char == "(":
            depth += 1
            buffer += char
        elif char == ")":
            depth = max(0, depth - 1)
            buffer += char
        elif depth > 0:
            buffer += char
        elif char in (">", "+", "~"):
            if buffer.strip():
                tokens.append(buffer.strip())
            buffer = ""
            tokens.append(char)
        elif char.isspace():
            if buffer.strip():
                tokens.append(buffer.strip())
            buffer = ""
            # 连续空格只产生一个后代组合器；已以组合器结尾时不重复添加
            if tokens and tokens[-1] not in (">", "+", "~", " "):
                tokens.append(" ")
        else:
            buffer += char
        index += 1

    if buffer.strip():
        tokens.append(buffer.strip())

    # 规整组合器：去掉首尾组合器，并消除相邻组合器。
    # 相邻组合器是写法冗余造成的（``p + p`` 在 ``+`` 前后各有一个空格，
    # 会同时产生后代组合器与 ``+``），保留最靠右的那个即可。
    cleaned: list[str] = []
    for token in tokens:
        is_combinator = token in (">", "+", "~", " ")
        if is_combinator and (not cleaned or cleaned[-1] in (">", "+", "~", " ")):
            # 连续组合器：用当前这个替换掉前一个（后者更贴近实际写法）
            if cleaned:
                cleaned[-1] = token
            continue
        cleaned.append(token)

    while cleaned and cleaned[0] in (">", "+", "~", " "):
        cleaned.pop(0)
    while cleaned and cleaned[-1] in (">", "+", "~", " "):
        cleaned.pop()
    return cleaned


#: 已实现的伪类
_SUPPORTED_PSEUDO = ("only-child", "only-of-type", "has")


def _match_chain(tag: Tag, chain: list[str]) -> bool:
    """按组合器从右向左求值选择器。

    选择器被切成"简单选择器 + 组合器"的交替序列，例如
    ``blockquote p + p`` → ``[blockquote] [p] + [p]``。

    从最右的简单选择器开始：它必须匹配当前元素；然后按左侧的组合器
    找到**用于继续验证的关联元素**（父 / 前一个兄弟 / 任意祖先），递归验证剩余部分。

    注意组合器可能出现在中间（``a + b c`` 这类写法），因此不能只从右端识别。
    """
    if not chain:
        return True

    # 从右往左找到第一个组合器，得到「最右简单选择器」与其余部分
    combinator_index = -1
    for index in range(len(chain) - 1, -1, -1):
        if chain[index] in (">", "+", "~", " "):
            combinator_index = index
            break

    if combinator_index == -1:
        # 没有组合器：整段必须匹配当前元素
        return all(_tag_matches(tag, token) for token in chain)

    combinator = chain[combinator_index]
    right = chain[combinator_index + 1 :]
    left = chain[:combinator_index]
    if not right:
        return False

    if not all(_tag_matches(tag, token) for token in right):
        return False

    if combinator == ">":
        parent = tag.parent
        return isinstance(parent, Tag) and _match_chain(parent, left)
    if combinator == "+":
        previous = tag.find_previous_sibling()
        return isinstance(previous, Tag) and _match_chain(previous, left)

    # 后代组合器：" " 与 "~" 都是"任一祖先匹配即可"
    ancestor = tag.parent
    while isinstance(ancestor, Tag):
        if _match_chain(ancestor, left):
            return True
        ancestor = ancestor.parent
    return False


def _tag_matches(tag: Tag, token: str) -> bool:
    """判断元素是否匹配选择器中的单个片段（标签名 + 可选的伪类）。"""
    if token == "*":
        return True

    name, pseudo = _split_pseudo(token)
    if name and tag.name != name:
        return False
    if pseudo is None:
        return True

    kind, argument = pseudo
    if kind == "only-child":
        return _is_only_child(tag)
    if kind == "only-of-type":
        return _is_only_of_type(tag)
    if kind == "has":
        return _has_matching_child(tag, argument or "")
    return False


def _split_pseudo(token: str) -> tuple[str, tuple[str, str | None] | None]:
    """把 ``blockquote:has(> blockquote:only-child)`` 拆成标签名与伪类。

    Returns:
        ``(标签名, (伪类名, 参数) 或 None)``。
    """
    if ":" not in token:
        return token, None

    name, _, rest = token.partition(":")
    if "(" in rest:
        kind, _, tail = rest.partition("(")
        return name, (kind.strip(), tail.rstrip(")").strip())
    return name, (rest.strip(), None)


def _is_only_child(tag: Tag) -> bool:
    """判断"整段只有这一处标记"。

    与 CSS 规范里的 ``:only-child`` **有意不同**：规范只看元素兄弟，
    因此 ``<p>前面文字 <strong>x</strong> 后面文字</p>`` 里的 ``strong``
    也算 only-child。但本项目要表达的是"整段就是这一处加粗"，
    周围有实际文字时不应触发。因此这里额外要求：除空白文本外，
    父元素下只有这一个标签子元素。

    （只把纯空白的文本节点排除在外——例如 ``<p><strong>x</strong></p>``
    里那个常伴随出现的空文本节点。）
    """
    parent = tag.parent
    if not isinstance(parent, Tag):
        return False

    tag_children: list[Tag] = []
    for child in parent.children:
        if isinstance(child, Tag):
            tag_children.append(child)
        elif isinstance(child, NavigableString) and child.strip():
            # 有实际文字 → 不是"整段只有这一处标记"
            return False
    return len(tag_children) == 1 and tag_children[0] is tag


def _is_only_of_type(tag: Tag) -> bool:
    """是否为父元素下唯一一个**同标签**的子元素。

    与 ``:only-child`` 的区别：同名的可以有多个兄弟，只要不同名即可。
    重点段落的判定需要它——``<blockquote><p><strong>x</strong></p></blockquote>``
    里那个 ``p`` 是唯一的 p，而两段引用的 ``p`` 不是。
    """
    parent = tag.parent
    if not isinstance(parent, Tag):
        return False
    same_type = [
        child
        for child in parent.children
        if isinstance(child, Tag) and child.name == tag.name
    ]
    return len(same_type) == 1 and same_type[0] is tag


def _has_matching_child(tag: Tag, argument: str) -> bool:
    """实现 ``:has()`` 的受限形式：参数为「相对选择器」。

    支持本项目需要的形式：以 ``>`` 开头的直接子代链，例如
    ``> blockquote:only-child``、``p > strong:only-child``。

    语义是「存在某个直接子元素，从它开始能匹配整条相对选择器」。

    不做完整的 CSS ``:has()``（任意组合器与嵌套组合）：收益与复杂度不成比例。
    看不懂的形式返回 False，而**不是**当作"不支持"静默放过——
    调用方（``_validate_selector``）已保证只有预期形式会走到这里。
    """
    target = argument.strip()
    if not target:
        return False

    # 以 ">" 开头表示直接子代；本项目未使用其他行首组合器
    if target.startswith(">"):
        target = target[1:].strip()
    if not target:
        return False

    # 按 ">" 切分后必须**先 strip 再判空**：
    # `p > strong` 会被切成 ["p ", " strong"]，若先判空会把带空格的段误判为空段，
    # 于是整条选择器静默返回 False。
    segments = [segment.strip() for segment in target.split(">")]
    segments = [segment for segment in segments if segment]
    if not segments:
        return False

    for child in tag.children:
        if isinstance(child, Tag) and _match_descendant_chain(child, segments):
            return True
    return False


def _match_descendant_chain(node: Tag, segments: list[str]) -> bool:
    """沿直接子代链逐段匹配；每一段可以包含多个简单选择器（如 ``strong:only-child``）。"""
    if not segments:
        return True

    head, rest = segments[0], segments[1:]
    for token in head.split():
        if not _tag_matches(node, token):
            return False

    if not rest:
        return True

    for child in node.children:
        if isinstance(child, Tag) and _match_descendant_chain(child, rest):
            return True
    return False


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
        numbered_headings: 自动加上编号的二级标题数量。
        has_byline: 是否插入了落款区。
    """

    html: str
    unstyled_tags: tuple[str, ...] = field(default=())
    warnings: tuple[str, ...] = field(default=())
    numbered_headings: int = 0
    has_byline: bool = False


def render_wechat_html(
    body_html: str,
    *,
    config: Config,
    stylesheet: StyleSheet | None = None,
    theme: str | None = None,
    container: bool = True,
    heading_numbers: bool | None = None,
    byline: str = "",
    byline_note: str = "",
) -> WechatRenderResult:
    """把规范化后的 HTML 渲染为微信兼容 HTML。

    Args:
        body_html: 正文 HTML 片段。
        config: 配置（提供字号、代码主题等）。
        stylesheet: 已解析的样式表；为 None 时按主题加载。
        theme: 主题名；为 None 时取配置里的 ``wechat.theme``。
        container: 是否套上正文容器标签。产物需要，预览外壳不需要。
        heading_numbers: 是否给二级标题自动编号；为 None 时取配置。
        byline: 落款区主行；为空则不渲染落款区。
        byline_note: 落款区副行。

    Returns:
        渲染结果。
    """
    sheet = stylesheet or load_stylesheet(config, theme or theme_name(config))
    soup = BeautifulSoup(body_html, "html.parser")

    _apply_code_highlighting(soup)
    _build_figures(soup, config, sheet)

    if heading_numbers is None:
        heading_numbers = _config_bool(config, "auto_number_headings", default=False)
    numbered = apply_heading_numbers(
        soup,
        enabled=heading_numbers,
        separator=_config_value(config, "heading_number_separator") or " · ",
        padding=int(_config_value(config, "heading_number_padding") or 2),
    )
    prepend_byline(soup, byline=byline, note=byline_note)
    has_byline = bool(byline.strip())

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
    _apply_config_overrides(soup, config, sheet)

    body = soup.body
    inner = "".join(str(child) for child in body.children) if body else str(soup)

    if not container:
        return WechatRenderResult(
            html=inner,
            unstyled_tags=tuple(unstyled),
            warnings=tuple(warnings),
            numbered_headings=numbered,
            has_byline=has_byline,
        )

    # 容器样式直接查规则表得到，不构造临时标签：
    # 在同一个 soup 上既取子节点又挂新容器，追加时会清空取到的内容。
    container_style = sheet.container_declarations()
    container_style.update(resolve_typography(config, sheet)["container"])
    if container_style:
        style_attr = to_style_attribute(container_style)
        return WechatRenderResult(
            html=f'<{ARTICLE_TAG} style="{style_attr}">{inner}</{ARTICLE_TAG}>',
            unstyled_tags=tuple(unstyled),
            warnings=tuple(warnings),
            numbered_headings=numbered,
            has_byline=has_byline,
        )
    return WechatRenderResult(
        html=f"<{ARTICLE_TAG}>{inner}</{ARTICLE_TAG}>",
        unstyled_tags=tuple(unstyled),
        warnings=tuple(warnings),
        numbered_headings=numbered,
        has_byline=has_byline,
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
    """把声明字典写成 ``style`` 属性值。

    会丢掉**被简写完全覆盖的长写**：若同时存在 ``border-left`` 与
    ``border-left-color``，只保留前者（``border-left`` 已包含颜色）。

    不这样做的话，产物里会留下 ``border-left:none; border-left-color:#4b5563``
    这类自相矛盾的组合——规范上简写获胜、结果正确，但读起来像是有意为之，
    而且顺序一旦被工具调整就会静默改变渲染。
    """
    effective = _drop_covered_longhands(declarations)
    return "".join(f"{name}:{value};" for name, value in effective.items())


#: 简写属性 → 它包含的长写属性
_SHORTHANDS: dict[str, tuple[str, ...]] = {
    "margin": ("margin-top", "margin-right", "margin-bottom", "margin-left"),
    "padding": ("padding-top", "padding-right", "padding-bottom", "padding-left"),
    "border": ("border-width", "border-style", "border-color"),
    "border-left": ("border-left-width", "border-left-style", "border-left-color"),
    "background": ("background-color", "background-image"),
    "font": ("font-size", "font-family", "font-weight", "line-height"),
}


def _drop_covered_longhands(declarations: dict[str, str]) -> dict[str, str]:
    """去掉已被简写属性覆盖的长写属性。"""
    result: dict[str, str] = {}
    for name, value in declarations.items():
        covered = any(
            name in longhands and shorthand in declarations
            for shorthand, longhands in _SHORTHANDS.items()
        )
        if covered:
            continue
        result[name] = value
    return result


def apply_heading_numbers(
    soup: BeautifulSoup, *, enabled: bool, separator: str = " · ", padding: int = 2
) -> int:
    """给二级标题自动编号：``Problem`` → ``01 · Problem``。

    只处理 ``h2``：``h1`` 是文章大标题，``h3`` 属于更细的分层，都不参与编号。
    正文里已经写了编号的标题会被识别并跳过，因此手工编号与自动编号不会叠加
    （``01 · Problem`` 不会变成 ``01 · 01 · Problem``）。

    Returns:
        实际加上编号的标题数量。
    """
    if not enabled:
        return 0

    count = 0
    for heading in soup.find_all("h2"):
        text = heading.get_text().strip()
        if not text:
            continue
        if _has_leading_number(text):
            # 作者已手写编号：跳过，但仍要占用序号以免后续编号错位
            count += 1
            continue
        number = str(count + 1).zfill(max(1, padding))
        heading.clear()
        heading.string = f"{number}{separator}{text}"
        count += 1
    return count


def _has_leading_number(text: str) -> bool:
    """判断标题是否已经以编号开头，如 ``01 ·``、``1.``、``01``。"""
    return re.match(r"^\s*\d{1,3}\s*(?:[.·、:：)）]|\s)", text) is not None


def prepend_byline(soup: BeautifulSoup, *, byline: str, note: str = "") -> bool:
    """在正文最前面插入落款区。

    落款区形态（对应参考账号的刊物式头部）：上方一道细线，居中一行小字刊名，
    其下可选一行更小的副标题。样式**直接内联**——产物零 class，
    不能依赖样式表里的类选择器。

    Returns:
        是否插入了落款区。
    """
    if not byline.strip():
        return False

    def styled(tag: Tag, declarations: dict[str, str], text: str) -> Tag:
        tag["style"] = to_style_attribute(declarations)
        tag.string = text
        return tag

    section = soup.new_tag("section")
    section["style"] = to_style_attribute(
        {
            "margin": "0 0 36px 0",
            "padding": "18px 0 0 0",
            "border-top": "1px solid #e5e7eb",
            "text-align": "center",
        }
    )
    section.append(
        styled(
            soup.new_tag("p"),
            {
                "margin": "0",
                "font-size": "13px",
                "line-height": "1.6",
                "font-weight": "700",
                "letter-spacing": "0.08em",
                "color": "#6b7280",
            },
            byline.strip(),
        )
    )
    if note.strip():
        section.append(
            styled(
                soup.new_tag("p"),
                {
                    "margin": "6px 0 0 0",
                    "font-size": "12px",
                    "line-height": "1.6",
                    "color": "#9ca3af",
                },
                note.strip(),
            )
        )

    body = soup.body
    target = body if body is not None else soup
    target.insert(0, section)
    return True


def _config_bool(config: Config, key: str, *, default: bool) -> bool:
    """读一个布尔配置项；缺失时返回默认值。

    YAML 里可能写成 ``true`` / ``"true"`` / ``yes``，这里统一按真假文本判断，
    避免"配置写了 true 却因为字符串类型被判为假"。
    """
    value = _config_value(config, key)
    if value is None:
        return default
    return value.strip().lower() in {"true", "yes", "on", "1"}


def _config_value(config: Config, key: str) -> str | None:
    """读一个渲染配置项；缺失或不可用时返回 None。

    这里**不做 strip**：部分配置项的首尾空格是有意义的——例如
    ``heading_number_separator: ' · '`` 依赖两端空格来分隔编号与标题，
    剥掉就会渲染成 ``01·Problem``。取值只做"是否为空"的判断。

    这里**只记录与覆盖**，不负责校验配置完整性——那是 config 层与 check 的职责。
    """
    try:
        value = config.wechat_value(key)
    except Exception:
        return None
    text = str(value)
    return text if text.strip() else None


def resolve_typography(config: Config, sheet: StyleSheet) -> dict[str, dict[str, str]]:
    """确定正文排版参数最终生效的取值。

    优先级 **主题 > 配置**：主题的职责就是决定节奏，配置只在主题未定义时补位。
    这样新增主题可以只写标题与卡片形式，正文参数自动沿用配置。

    渲染与 ``render_options`` 记录**共用本函数**，因此"记录 = 产物"由结构保证，
    而不是靠两处各写一遍再人工对齐。

    间距统一用**一个 ``margin`` 简写**输出，不混用 ``margin`` 与 ``margin-bottom``：
    两者并存时哪条生效取决于书写顺序，产物里同时出现会变成难以判断的写法。

    Returns:
        ``{"container": {...}, "paragraph": {...}}``，值为可直接写入 style 的属性。
    """
    container = sheet.container_declarations()

    font_size = container.get("font-size") or _px(_config_value(config, "font_size") or "")
    line_height = container.get("line-height") or _config_value(config, "line_height") or ""

    paragraph: dict[str, str] = {}
    if font_size:
        paragraph["font-size"] = font_size
    if line_height:
        paragraph["line-height"] = line_height

    margin = _resolve_paragraph_margin(config, sheet)
    if margin:
        paragraph["margin"] = margin

    resolved_container: dict[str, str] = {}
    if font_size:
        resolved_container["font-size"] = font_size
    if line_height:
        resolved_container["line-height"] = line_height

    return {"container": resolved_container, "paragraph": paragraph}


def _resolve_paragraph_margin(config: Config, sheet: StyleSheet) -> str:
    """确定正文段落的 margin，返回简写形式。

    以主题声明的 margin 为基准，只把**主题未给出**的方向用配置补齐。
    这样不会出现"主题给简写、配置给长写"的冲突。
    """
    parts = _parse_margin(_paragraph_margin(sheet))
    spacing = _px(_config_value(config, "paragraph_spacing") or "")
    if spacing and not parts[2]:
        parts[2] = spacing
    if not any(parts):
        return ""

    top, right, bottom, left = parts
    if left == right:
        if top == bottom:
            return f"{top or '0'} {right or '0'}"
        return f"{top or '0'} {right or '0'} {bottom or '0'}"
    return f"{top or '0'} {right or '0'} {bottom or '0'} {left or '0'}"


#: margin 简写解出的四个方向，顺序为 上 右 下 左
_MARGIN_SLOTS = 4


def _parse_margin(value: str) -> list[str]:
    """把 margin 简写解成 ``[上, 右, 下, 左]``；缺省方向按 CSS 规则展开。"""
    tokens = value.split() if value else []
    if not tokens:
        return [""] * _MARGIN_SLOTS
    if len(tokens) == 1:
        return [tokens[0]] * _MARGIN_SLOTS
    if len(tokens) == 2:
        return [tokens[0], tokens[1], tokens[0], tokens[1]]
    if len(tokens) == 3:
        return [tokens[0], tokens[1], tokens[2], tokens[1]]
    return tokens[:_MARGIN_SLOTS]


def _paragraph_margin(sheet: StyleSheet) -> str:
    """从样式表取段落 margin 简写；取不到时返回空串。"""
    for selector, declarations in sheet.rules:
        if selector == "p":
            return declarations.get("margin", "")
    return ""


def _apply_config_overrides(soup: BeautifulSoup, config: Config, sheet: StyleSheet) -> None:
    """把 :func:`resolve_typography` 的结果写到段落的 ``style`` 上。

    只在段落**尚无**对应声明时补上，不覆盖模板或着色阶段已写入的样式。
    """
    typography = resolve_typography(config, sheet)
    for tag in soup.find_all("p"):
        existing = tag.get("style")
        current = existing if isinstance(existing, str) else ""
        overrides = {
            name: value
            for name, value in typography["paragraph"].items()
            if f"{name}:" not in current
        }
        if overrides:
            tag["style"] = merge_styles(
                existing if isinstance(existing, str) else None, overrides
            )


def _px(value: str) -> str:
    """补上 px 单位；已经是长度值时原样返回。"""
    return value if value.endswith(("px", "%", "em", "rem")) else f"{value}px"


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
