"""内容索引：扫描文章并生成内容目录下的 INDEX.md（任务书 §14）。

设计要点：

- **索引跟随内容。** 索引描述的是文章，而文章位于 ``content_root``；
  内容与工具分离后（任务书 §3），索引也写在 ``<content_root>/INDEX.md``，
  这样作者打开自己的内容目录就能看到总览。工具仓库的 README 不再列举作者的文章。
- **只替换标记之间的区块。** 文件里其余内容属于人写的部分，程序不得改动。
  这既是"唯一事实源"纪律的延伸，也避免每次生成都把人工编排的说明冲掉。
- **找不到标记时报错，不盲目追加。** ``INDEX.md`` 可能是作者自己写的文件；
  在它末尾悄悄追加一段程序生成的表格，等于未经允许改动用户文件。
  文件不存在时才创建，存在但缺标记时要求作者先补标记（或显式 --force 覆盖）。
- **同一份数据同时服务 INDEX.md 与将来的机器可读清单。**
  因此这里先产出结构化的 :class:`IndexEntry`，再由不同渲染函数消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from inloop.articles import ArticleLocation, find_articles
from inloop.fsutil import write_text
from inloop.models.article import Article, ArticleError, Category

#: 索引区块的起止标记
INDEX_BEGIN = "<!-- inloop:index:begin -->"
INDEX_END = "<!-- inloop:index:end -->"

#: 索引文件名（写在内容目录下）
INDEX_FILE_NAME = "INDEX.md"

#: 新建索引文件时的抬头。只在文件不存在时写入，之后由作者自由修改。
_INDEX_HEADER = """# 文章索引

本文件由 `inloop index` 维护「文章列表」区块，**区块以外的内容可以自由编辑**。

<!-- 程序只替换下面两个标记之间的内容，不要删除标记。 -->

"""


class IndexError_(RuntimeError):
    """索引生成失败。命名带下划线以避免与内置 ``IndexError`` 冲突。"""


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """索引中的一篇文章。

    Attributes:
        number: 文章编号。
        title: 标题。
        slug: 产物短名（含序号，形如 ``002-light-o1``）。
        date: 日期字符串。
        category: 栏目。
        status: 状态。
        tags: 标签。
        summary: 摘要。
        path: 相对仓库根的正文路径。
    """

    number: int
    title: str
    slug: str
    date: str
    category: Category
    status: str
    tags: tuple[str, ...]
    summary: str
    path: str


def collect_entries(content_root: Path) -> list[IndexEntry]:
    """扫描内容目录，收集索引条目。

    某篇文章解析失败时**不中断整体**，而是抛出带明确位置的错误——
    索引是给人看的汇总，宁可整体报错也不要悄悄少一行。
    """
    entries: list[IndexEntry] = []
    for location in find_articles(content_root):
        article = _load(location)
        entries.append(
            IndexEntry(
                number=article.id,
                title=article.title,
                slug=article.directory_name,
                date=article.date.isoformat(),
                category=article.category,
                status=str(article.status),
                tags=article.tags,
                summary=article.summary,
                # 索引与文章同在内容目录下，因此用**相对内容目录**的路径，
                # 这样在 Obsidian 里点击即可跳转，也不泄漏本机绝对路径。
                path=location.index.relative_to(content_root).as_posix(),
            )
        )
    return entries


def render_index(entries: list[IndexEntry]) -> str:
    """把索引渲染成 README 中的区块（含起止标记）。"""
    lines = [INDEX_BEGIN, ""]

    if not entries:
        lines.append("暂无文章。新建文章：`inloop new --title \"标题\" --slug your-slug`")
        lines.append("")
        lines.append(INDEX_END)
        return "\n".join(lines)

    lines.append(f"共 {len(entries)} 篇。")
    lines.append("")
    lines.append("| ID | 日期 | 栏目 | 标题 | 状态 | 标签 |")
    lines.append("|---|---|---|---|---|---|")

    for entry in entries:
        tags = "、".join(entry.tags) if entry.tags else "—"
        title_link = f"[{_escape_table(entry.title)}]({entry.path})"
        lines.append(
            f"| {entry.number:03d} "
            f"| {entry.date} "
            f"| {entry.category.label} "
            f"| {title_link} "
            f"| {entry.status} "
            f"| {_escape_table(tags)} |"
        )

    lines.append("")
    lines.append(INDEX_END)
    return "\n".join(lines)


def update_index_file(
    content_root: Path,
    entries: list[IndexEntry],
    *,
    allow_create: bool = True,
    force: bool = False,
) -> tuple[bool, int]:
    """把索引写入 ``<content_root>/INDEX.md``。

    Args:
        content_root: 内容目录。
        entries: 索引条目。
        allow_create: 文件不存在时是否允许创建。
        force: 文件存在但没有标记时，是否整份覆盖。

    Returns:
        ``(是否有变化, 条目数)``。

    Raises:
        IndexError_: 文件存在但缺少标记，且未指定 ``force``。
    """
    target = content_root / INDEX_FILE_NAME

    if not target.is_file():
        if not allow_create:
            raise IndexError_(
                f"索引文件不存在：{target}\n"
                f"修正方法：去掉 `--check` 让它生成；"
                f"或先创建该文件并写入标记 {INDEX_BEGIN} 与 {INDEX_END}。"
            )
        text = f"{_INDEX_HEADER}{render_index(entries)}\n"
        write_text(target, text)
        return True, len(entries)

    text = target.read_text(encoding="utf-8")
    block = render_index(entries)

    if INDEX_BEGIN in text and INDEX_END in text:
        pattern = re.compile(
            re.escape(INDEX_BEGIN) + r".*?" + re.escape(INDEX_END),
            flags=re.DOTALL,
        )
        updated = pattern.sub(lambda _: block, text)
    elif force:
        # 显式要求覆盖：连作者写的内容一起替换，抬头重新生成
        updated = f"{_INDEX_HEADER}{block}\n"
    else:
        # 关键分支：**不盲目追加**。
        # 这个文件可能是作者自己写的，在里面塞一段程序生成的表格等于擅自改动用户文件。
        raise IndexError_(
            f"索引文件缺少标记，未做修改：{target}\n"
            f"  需要这两个标记才能安全地只替换列表部分：\n"
            f"    {INDEX_BEGIN}\n"
            f"    {INDEX_END}\n"
            f"修正方法（任选其一）：\n"
            f"  1. 自己在该文件里加上上面两行标记，程序会只替换它们之间的内容；\n"
            f"  2. 运行 `inloop index --force`，用生成的索引**整份覆盖**该文件"
            f"（原有内容会丢失）；\n"
            f"  3. 把该文件改名或移到别处，让程序重新生成一份。"
        )

    if updated == text:
        return False, len(entries)

    write_text(target, updated)
    return True, len(entries)


def check_index_file(content_root: Path, entries: list[IndexEntry]) -> tuple[bool, str]:
    """检查索引文件是否为最新。

    Returns:
        ``(是否为最新, 说明文字)``。
    """
    target = content_root / INDEX_FILE_NAME
    if not target.is_file():
        return False, f"索引文件不存在：{target}"
    text = target.read_text(encoding="utf-8")
    if INDEX_BEGIN not in text or INDEX_END not in text:
        return False, f"索引文件缺少标记：{target}"
    match = re.search(
        re.escape(INDEX_BEGIN) + r".*?" + re.escape(INDEX_END), text, flags=re.DOTALL
    )
    assert match is not None
    return match.group(0) == render_index(entries), ""


def _load(location: ArticleLocation) -> Article:
    try:
        return Article.from_text(
            location.index.read_text(encoding="utf-8"), source=location.index
        )
    except ArticleError as exc:
        raise IndexError_(
            f"文章无法解析，索引未生成：{location.index}\n{exc}"
        ) from exc


def _escape_table(text: str) -> str:
    """转义 Markdown 表格中会破坏结构的字符。"""
    return text.replace("|", "\\|").replace("\n", " ")
