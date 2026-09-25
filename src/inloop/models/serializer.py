"""Front Matter 序列化：把模型写回 Markdown。

与 :mod:`inloop.parser.frontmatter` 互为逆操作。放在模型层旁边，是因为
「字段顺序、引号策略、枚举怎么写回文本」都是模型的语义决定，不是文件 IO。

两个必须处理的细节：

1. **``StrEnum`` 无法被 PyYAML 直接序列化。** PyYAML 的 representer 表按
   ``type(data)`` 精确匹配，``Category`` 不等于 ``str``，于是 ``safe_dump`` 会
   抛 ``RepresenterError``。这里显式注册 ``StrEnum`` 的 representer，
   让枚举以纯字符串写出（而不是 ``!!python/object`` 之类的标签）。
2. **中文必须 ``allow_unicode=True``。** 否则中文会被转义成 ``\\u4E2D\\u6587``，
   源文件将变得不可读——而文章源文件是给人读的。
"""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml

from inloop.fsutil import write_text
from inloop.models.article import Article

#: Front Matter 的字段顺序。
#: 顺序即阅读顺序：先身份（id/title/slug），再时间与分类，最后标签与平台。
#: 固定顺序让 diff 稳定——否则每次生成都可能因字典顺序变化产生无意义差异。
FIELD_ORDER: tuple[str, ...] = (
    "id",
    "title",
    "slug",
    "date",
    "author",
    "category",
    "status",
    "tags",
    "summary",
    "cover",
    "platforms",
)

#: 发布平台键的稳定顺序；未列出的平台按字母序追加在后。
_PLATFORM_ORDER: tuple[str, ...] = ("wechat", "blog", "zhihu", "xiaohongshu", "bilibili")

#: 尽量不折行：文章元数据里有长摘要，折行会让 diff 变脏。
_WIDTH = 4096


class _FrontMatterDumper(yaml.SafeDumper):
    """只输出基础类型的 dumper，额外支持 ``StrEnum``。

    ``increase_indent`` 是 PyYAML 的公开扩展点：默认序列化会写成

        tags:
        - Humanoid

    两级缩进对 YAML 合法，但读起来列表像是脱离了键。这里改为两个空格缩进：

        tags:
          - Humanoid
    """

    def increase_indent(self, flow: bool = False, indentless: bool = False) -> None:
        super().increase_indent(flow=flow, indentless=False)


def _represent_str_enum(dumper: yaml.SafeDumper, data: StrEnum) -> yaml.Node:
    """把 ``StrEnum`` 写成普通字符串。"""
    return dumper.represent_str(str(data))


def _represent_none(dumper: yaml.SafeDumper, _: None) -> yaml.Node:
    """空值写成空字符串，而不是 ``null``。

    理由：``summary: null`` 看起来像程序写坏的数据，``summary: ""`` 至少明确
    表示「这里确实没有内容」。也避免 YAML 里 ``null``/``~``/空 三种写法混用。
    """
    return dumper.represent_str("")


_FrontMatterDumper.add_multi_representer(StrEnum, _represent_str_enum)
_FrontMatterDumper.add_representer(type(None), _represent_none)


class SerializationError(ValueError):
    """模型无法序列化（通常是含无法表达的值）。"""


def dump_front_matter(meta: dict[str, Any]) -> str:
    """把元数据字典序列化为 front matter 文本（不含定界符）。

    Args:
        meta: 元数据。

    Returns:
        YAML 文本，UTF-8 中文不转义，键按 :data:`FIELD_ORDER` 排序。
    """
    ordered = _order_fields(meta)
    try:
        text = yaml.dump(
            ordered,
            Dumper=_FrontMatterDumper,
            allow_unicode=True,
            sort_keys=False,
            width=_WIDTH,
            default_flow_style=False,
        )
    except yaml.YAMLError as exc:  # pragma: no cover - 正常路径不会触发
        raise SerializationError(
            f"front matter 序列化失败：{exc}。\n"
            "修正方法：检查字段值是否包含无法表示为 YAML 的对象。"
        ) from exc
    return text.rstrip("\n")


def article_meta(article: Article) -> dict[str, Any]:
    """把 :class:`Article` 转成可序列化的元数据字典。

    ``extra`` 中未被模型识别的字段会原样带出，保证「解析再写回」不丢字段。
    """
    meta: dict[str, Any] = {
        "id": article.id,
        "title": article.title,
        "slug": article.slug,
        "date": article.date,
        "author": article.author,
        "category": str(article.category),
        "status": str(article.status),
        "tags": list(article.tags),
        "summary": article.summary,
        "cover": article.cover,
        "platforms": _order_platforms(article.platforms),
    }
    # 未知字段追加在已知字段之后，保留作者原始意图
    for key, value in article.extra.items():
        if key not in meta:
            meta[key] = value
    return meta


def render_article_text(article: Article, body: str | None = None) -> str:
    """把文章渲染为完整的 Markdown 文本（front matter + 正文）。

    Args:
        article: 文章模型。
        body: 正文。为 None 时使用 ``article.body``。

    Returns:
        完整文本，以换行结尾。换行统一为 LF（AGENTS.md §4）。
    """
    text_body = article.body if body is None else body
    front = dump_front_matter(article_meta(article))
    # 正文统一以单个换行结尾，避免出现多个连续空行或缺失结尾换行
    normalized_body = text_body.replace("\r\n", "\n").replace("\r", "\n").strip("\n")
    return f"---\n{front}\n---\n\n{normalized_body}\n"


def write_article(article: Article, path: Path, body: str | None = None) -> Path:
    """把文章写入文件。

    写入采用「先写临时文件再替换」，避免中断时留下半截文件；
    并带重试以跨过 Windows 上的瞬时文件占用（见 :mod:`inloop.fsutil`）。

    Returns:
        实际写入的路径。
    """
    text = render_article_text(article, body=body)
    return write_text(path, text)


# --- 内部辅助 -------------------------------------------------------------


def _order_fields(meta: dict[str, Any]) -> dict[str, Any]:
    """按 :data:`FIELD_ORDER` 重排键，未知键按字母序追加。"""
    ordered: dict[str, Any] = {}
    for key in FIELD_ORDER:
        if key in meta:
            ordered[key] = meta[key]
    for key in sorted(k for k in meta if k not in ordered):
        ordered[key] = meta[key]
    return ordered


def _order_platforms(platforms: dict[str, bool]) -> dict[str, bool]:
    """按固定顺序排列平台开关。"""
    ordered: dict[str, bool] = {}
    for key in _PLATFORM_ORDER:
        if key in platforms:
            ordered[key] = platforms[key]
    for key in sorted(k for k in platforms if k not in ordered):
        ordered[key] = platforms[key]
    return ordered
