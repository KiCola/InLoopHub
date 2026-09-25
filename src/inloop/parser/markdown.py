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

## Obsidian 嵌入语法

作者用 Obsidian 写作，插图时自然会用 ``![[图片名.png]]``（Obsidian 的嵌入语法），
而 markdown-it 只认标准语法 ``![](路径)``——于是嵌入会**原样显示成一行文字**，
图不出现。这是实测踩到的问题（用户从剪贴板粘图就会这样）。

因此这里把嵌入语法**归一化为标准图片语法**再交给解析器：

    ![[图.png]]              →  ![图.png](assets/图.png)
    ![[图.png|说明文字]]      →  ![说明文字](assets/图.png)
    ![[图.png|300]]          →  ![图.png](assets/图.png "300")   （宽度提示）
    ![[图.png|300|说明文字]]  →  ![说明文字](assets/图.png "300")

真实路径由调用方通过 ``resolve_embed`` 提供（它有文件系统访问权，能处理
"图片其实在 assets/ 子目录里"这类情况）；不传时按 ``assets/<文件名>`` 约定。
解析不到的嵌入会产出 ERROR（``IMG105``），而不是留下一行看不懂的文字。
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from markdown_it import MarkdownIt
from mdit_py_plugins.dollarmath import dollarmath_plugin
from mdit_py_plugins.footnote import footnote_plugin
from mdit_py_plugins.tasklists import tasklists_plugin

from inloop.rules import (
    EMBED_NOT_FOUND,
    MD_MATH_UNSUPPORTED,
    MD_RAW_FOOTNOTE,
    Rule,
)


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


def render_markdown(
    text: str,
    resolve_embed: Callable[[str], str | None] | None = None,
) -> MarkdownRenderResult:
    """把 Markdown 正文渲染为 HTML 片段。

    Args:
        text: 正文 Markdown（不含 front matter）。
        resolve_embed: 把 Obsidian 嵌入的文件名解析为可用的相对路径。
            不传时按 ``assets/<文件名>`` 约定。解析失败请返回 None，
            这里会产出 ``IMG105`` ERROR 而不是留一行看不懂的文字。

    Returns:
        渲染结果；若存在脚注、公式或解析不到的嵌入，``warnings`` 会包含对应提示。

    Raises:
        MarkdownRenderError: 解析器抛出异常（正常情况下不应发生）。
    """
    # 先归一化 Obsidian 嵌入语法，再交给 markdown-it。
    # 顺序不能反：markdown-it 认不出 ![[...]]，会把整行当普通文字。
    text, embed_issues = convert_obsidian_embeds(text, resolve_embed)

    try:
        html = _PARSER.render(text)
    except Exception as exc:  # pragma: no cover - 解析器本身极少失败
        raise MarkdownRenderError(
            f"Markdown 渲染失败：{exc}\n"
            "修正方法：检查正文中是否存在未闭合的代码块（```）或表格分隔行。"
        ) from exc

    warnings = list(_collect_warnings(text, html))
    warnings.extend(embed_issues)
    return MarkdownRenderResult(html=html, warnings=tuple(warnings))


#: 匹配 Obsidian 嵌入语法 ``![[...]]``。
#: 文件名里可能含空格与中文，因此用非贪婪到第一个 ``]]``。
_EMBED = re.compile(r"!\[\[([^\[\]]+?)\]\]")

#: 会被当作"尺寸提示"而不是说明文字的目标值（纯数字，可选 px）
_SIZE_HINT = re.compile(r"^\d+(?:px)?$", re.IGNORECASE)

#: 这些扩展名才按图片处理；其他（如 ``![[笔记]]``）不转换，
#: 避免把笔记嵌入误改成图片引用。
_IMAGE_SUFFIXES = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".bmp",
    ".svg",
    ".avif",
)


def _needs_angle_brackets(target: str) -> bool:
    """路径是否需要用 ``<...>`` 包起来才能被 Markdown 识别为链接目标。

    CommonMark 规定：未加尖括号的链接目标**不能含空格或控制字符**。
    含空格时若不加尖括号，整段不会被解析成图片，而是原样显示成一行文字——
    图片"消失"且毫无提示，是最难自查的一类问题。
    """
    return any(char.isspace() for char in target) or any(
        ord(char) < 0x20 for char in target
    )


def convert_obsidian_embeds(
    text: str,
    resolve_embed: Callable[[str], str | None] | None = None,
) -> tuple[str, tuple[str, ...]]:
    """把 Obsidian 嵌入语法转成标准 Markdown 图片语法。

    只处理**看起来是图片**的嵌入（按扩展名判断）：``![[某篇笔记]]`` 这类
    笔记嵌入不做转换，否则会把正文里的笔记引用改成图片引用，问题更大。

    Args:
        text: 正文 Markdown。
        resolve_embed: 文件名 → 相对路径。返回 None 表示找不到。

    Returns:
        ``(转换后的文本, 问题提示)``。找不到的嵌入会在提示里说明**期望放在哪里**。
    """
    issues: list[str] = []

    def replace(match: re.Match[str]) -> str:
        inner = match.group(1).strip()
        # Obsidian 的写法是 `文件名|参数|参数`，参数可以是说明文字或尺寸
        parts = [part.strip() for part in inner.split("|")]
        name = parts[0]
        extras = [part for part in parts[1:] if part]

        if not name.lower().endswith(_IMAGE_SUFFIXES):
            # 不是图片（多半是笔记嵌入），原样保留
            return match.group(0)

        alt = ""
        title = ""
        for extra in extras:
            if _SIZE_HINT.match(extra):
                # 尺寸提示没有标准 Markdown 对应物，放进 title 供渲染层按需使用
                title = title or extra
            else:
                alt = alt or extra

        target = resolve_embed(name) if resolve_embed is not None else None
        if target is None:
            if resolve_embed is not None:
                issues.append(
                    f"{EMBED_NOT_FOUND.code} [{EMBED_NOT_FOUND.level.value}] "
                    f"找不到嵌入的图片 `{name}`\n"
                    f"    修正方法：把图片放到文章的 `assets/` 目录下，"
                    f"或改用标准写法 `![说明](assets/{name})`。"
                )
                # 找不到时退化为**带反引号的文字**，让它在成品里也明显是"有问题"，
                # 而不是悄悄变成一句普通的话。
                return f"`[图片缺失：{name}]`"
            # 没有解析器（纯语法转换场景）时按约定拼出 assets 路径
            target = f"assets/{name}"

        # 标准语法：![alt](path "title")
        escaped_alt = alt.replace("[", "\\[").replace("]", "\\]")
        suffix = f' "{title}"' if title else ""
        # **路径含空格时必须用尖括号包起来**：CommonMark 规定「未加尖括号的
        # 链接目标不能含空格」，否则整段不会被识别为图片、而是原样显示成文字。
        # 而 Obsidian 从剪贴板粘进来的截图文件名普遍带空格
        # （例如「屏幕截图 2026-09-18 191232.png」），这直接决定图片能不能出现。
        target_ref = f"<{target}>" if _needs_angle_brackets(target) else target
        return f"![{escaped_alt}]({target_ref}{suffix})"

    converted = _EMBED.sub(replace, text)
    return converted, tuple(issues)


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
