"""渲染选项的留存与展示。

解决的问题：**"这篇文章是用哪套样式渲染出来的"必须可查。**

样式会被不断调整，文章则长期存在。如果产物里不记录渲染选项，半年后回看
一篇已发布的文章，无法回答"当时的标题是下划线还是底块、行高是多少"，
也就无法复现同样的观感——这正是"主题要能切换与复用"的前提。

因此：

- 构建时把生效的选项写进 ``metadata.json`` 的 ``render_options``；
- 同时把主题名写进 HTML 的 ``<meta name="inloop:theme">``，
  使单看一个 HTML 文件也能知道它是哪个主题渲染的；
- ``inloop themes`` 展示每个主题的定位与关键数值，方便挑选与对比。

这里只做**记录与展示**，不改渲染行为——渲染仍由样式表决定。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from inloop.config import Config
from inloop.renderer.wechat import StyleSheet, available_themes, resolve_typography

#: HTML 中记录主题的 meta 名
THEME_META_NAME = "inloop:theme"

#: 主题文件顶部注释里的定位说明行，形如 `定位：xxx`
_PURPOSE_PATTERN = re.compile(r"^\s*风格定位[:：]\s*(?P<text>.+?)\s*$", re.MULTILINE)

#: 从主题文件注释中抽取的说明最大长度
_PURPOSE_MAX_CHARS = 80


@dataclass(frozen=True, slots=True)
class RenderOptions:
    """一次渲染实际生效的选项快照。

    这些值全部来自产物当时的样式与配置，因此可作为"复现这次观感"的依据。
    """

    theme: str
    body_font_size: str
    body_line_height: str
    paragraph_spacing: str
    heading_style: str
    code_theme: str
    image_max_width: str
    inline_css: bool

    def as_metadata(self) -> dict[str, object]:
        """转成写进 ``metadata.json`` 的字典。

        键序固定：便于 diff，也便于人工比对两篇文章的渲染差异。
        """
        return {
            "theme": self.theme,
            "body_font_size": self.body_font_size,
            "body_line_height": self.body_line_height,
            "paragraph_spacing": self.paragraph_spacing,
            "heading_style": self.heading_style,
            "code_theme": self.code_theme,
            "image_max_width": self.image_max_width,
            "inline_css": self.inline_css,
        }


def collect_render_options(
    config: Config, *, theme: str, stylesheet: StyleSheet
) -> RenderOptions:
    """汇总本次渲染实际生效的选项。

    取值直接调用渲染层使用的 :func:`~inloop.renderer.wechat.resolve_typography`，
    因此"记录 = 产物"由结构保证，而不是靠两处各写一遍再人工对齐——
    记录与实际不符比不记录更糟：会让人以为观感是 A，实际是 B。
    """
    resolved = resolve_typography(config, stylesheet)
    container = resolved["container"]
    paragraph = resolved["paragraph"]

    return RenderOptions(
        theme=theme,
        body_font_size=container.get("font-size", ""),
        body_line_height=container.get("line-height", ""),
        paragraph_spacing=_bottom_margin(paragraph.get("margin", "")),
        heading_style=_config_text(config, "heading_style"),
        code_theme=_config_text(config, "code_theme"),
        image_max_width=_config_text(config, "image_max_width"),
        inline_css=bool(config.wechat_value("inline_css")),
    )


def _bottom_margin(margin: str) -> str:
    """从 margin 简写里取出**下边距**，用于记录段落间距。

    段落间距统一以 ``margin`` 简写写入产物，这里按 CSS 的展开规则取第三个值
    （一个值时四个方向相同，两个值时上下取第一个）。
    """
    tokens = margin.split()
    if not tokens:
        return ""
    if len(tokens) == 1:
        return tokens[0]
    if len(tokens) == 2:
        return tokens[0]
    return tokens[2]


def _config_text(config: Config, key: str) -> str:
    """读配置项并转成文本；缺失时返回空串而不是抛异常。

    这里只用于**记录**，不应因为某个配置键缺失就让构建失败——
    校验配置完整性是 config 层与校验命令的职责。
    """
    try:
        value = config.wechat_value(key)
    except Exception:
        return ""
    return str(value)


def theme_purpose(config: Config, theme: str) -> str:
    """从主题文件的注释里读一句定位说明，用于 ``inloop themes`` 展示。"""
    path = config.root / "styles" / "themes" / f"{theme}.css"
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8")
    match = _PURPOSE_PATTERN.search(text)
    if match is None:
        return ""
    purpose = match.group("text").strip()
    return purpose[:_PURPOSE_MAX_CHARS]


def describe_themes(config: Config) -> list[tuple[str, str]]:
    """列出全部主题及其中文定位，供 CLI 展示。"""
    return [(name, theme_purpose(config, name)) for name in available_themes(config)]


def read_theme_from_html(html: str) -> str:
    """从产物 HTML 中读回渲染时使用的主题名。

    用于"手上只有一个 HTML 文件"的场景——例如从别处拿到的产物，
    也能判断它是哪个主题渲染的。
    """
    pattern = re.compile(
        rf'<meta\s+name="{re.escape(THEME_META_NAME)}"\s+content="(?P<theme>[^"]*)"\s*/?>'
    )
    match = pattern.search(html)
    return match.group("theme") if match else ""


def theme_meta_tag(theme: str) -> str:
    """生成记录主题的 meta 标签。"""
    return f'<meta name="{THEME_META_NAME}" content="{theme}">'
