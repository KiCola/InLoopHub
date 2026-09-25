"""Markdown → HTML 渲染。

职责边界（AGENTS.md §7、docs/architecture.md 第 2 节）：

- **负责**：Markdown 正文 → 语义化的 HTML 片段。
- **不负责**：加样式（在 :mod:`inloop.renderer.wechat`）、动图片路径
  （由渲染层依据素材清单统一改写）、写文件。

这里刻意**不加任何样式属性**。样式只有一个施加点，就是微信渲染层；
如果这里也写一点 style，最终哪些样式来自哪里将无法追溯。

两个微信端无法成立、必须在这里就处理掉的语法：

- **脚注**：markdown-it 产出的是 ``<a href="#fn1">`` 锚点跳转。微信正文里
  锚点跳转不可用（点击不会跳，且锚点 id 会被编辑器丢弃），因此改为文末的
  有序列表，并把全角上标引用改成 ``[1]`` 形式。
- **公式**：数学排版需要 JS 或 MathML，两者微信都不支持。保留 LaTeX 原文
  并按等宽文本呈现——至少内容不丢失，读者仍能看懂公式含义。

两者都会产出 WARNING（规则码 ``MD101`` / ``MD103``），因为「内容被降级」
是使用者必须知道的事实，不能悄悄发生。
"""

from __future__ import annotations

from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from inloop.rules import MD_MATH_UNSUPPORTED, MD_RAW_FOOTNOTE, Rule


@dataclass(frozen=True, slots=True)
class MarkdownRenderResult:
    """渲染结果。

    Attributes:
        html: HTML 片段。
        warnings: 渲染过程中的降级提示，需在 CLI 中原样展示。
    """

    html: str
    warnings: tuple[str, ...] = field(default=())


def build_parser() -> MarkdownIt:
    """构造本项目的 Markdown 解析器。

    以 ``commonmark`` 为基线而不是 ``gfm-like``：后者会引入 linkify 依赖，
    而任务书 §21 的依赖清单里没有它。表格与删除线是内置规则，直接开启即可。
    """
    md = MarkdownIt("commonmark")
    # 内置规则，commonmark 预设未启用
    md.enable("table")
    md.enable("strikethrough")
    # 任务书 §5 要求支持脚注、公式、任务列表
    md = md.use(footnote_plugin).use(dollarmath_plugin).use(tasklists_plugin)
    return md


#: 模块级解析器实例。MarkdownIt 的规则配置在构造后不再变化，可安全复用。
_PARSER = build_parser()


def render_markdown(text: str) -> MarkdownRenderResult:
    """把 Markdown 正文渲染为 HTML 片段。

    Args:
        text: 正文 Markdown（不含 front matter）。

    Returns:
        渲染结果；若存在脚注或公式，``warnings`` 会包含对应的降级提示。

    Raises:
        MarkdownRenderError: 解析器抛出异常（正常情况下不应发生）。
    """
    try:
        html = _PARSER.render(text)
    except Exception as exc:  # pragma: no cover - 解析器本身极少失败
        raise MarkdownRenderError(
            f"Markdown 渲染失败：{exc}\n"
            "修正方法：检查正文中是否存在未闭合的代码块（```）或表格分隔行。"
        ) from exc

    return MarkdownRenderResult(html=html, warnings=_collect_warnings(text, html))


class MarkdownRenderError(ValueError):
    """Markdown 渲染失败。"""


def _collect_warnings(source: str, html: str) -> tuple[str, ...]:
    """收集渲染过程中的降级提示。"""
    warnings: list[str] = []

    if "footnote-ref" in html or "footnotes" in html:
        warnings.append(_describe(MD_RAW_FOOTNOTE))
    if "math inline" in html or "math block" in html:
        warnings.append(_describe(MD_MATH_UNSUPPORTED))

    return tuple(warnings)


def _describe(rule: Rule) -> str:
    return f"{rule.code} [{rule.level.value}] {rule.summary}"
