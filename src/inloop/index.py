"""内容索引：扫描文章并生成 README 中的索引区块（任务书 §14）。

设计要点：

- **只替换标记之间的区块。** README 里其余内容属于人写的部分，程序不得改动。
  这既是"唯一事实源"纪律的延伸，也避免每次生成都把人工编排的说明冲掉。
- **同一份数据同时服务 README 与将来的 ``dist/metadata/articles.json``。**
  因此这里先产出结构化的 :class:`IndexEntry`，再由不同渲染函数消费。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from inloop.articles import ArticleLocation, find_articles
from inloop.models.article import Article, ArticleError, Category

#: 索引区块的起止标记
INDEX_BEGIN = "<!-- inloop:index:begin -->"
INDEX_END = "<!-- inloop:index:end -->"

#: README 文件名
README_NAME = "README.md"


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


def collect_entries(root: Path) -> list[IndexEntry]:
    """扫描文章目录，收集索引条目。

    某篇文章解析失败时**不中断整体**，而是抛出带明确位置的错误——
    索引是给人看的汇总，宁可整体报错也不要悄悄少一行。
    """
    entries: list[IndexEntry] = []
    for location in find_articles(root):
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
                # README 里的链接要能在 GitHub 上点开，因此用相对仓库根的路径
                path=location.index.relative_to(root).as_posix(),
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


def update_readme(root: Path, entries: list[IndexEntry]) -> tuple[bool, int]:
    """把索引写入 README。

    Returns:
        ``(是否有变化, 条目数)``。
    """
    readme = root / README_NAME
    if not readme.is_file():
        raise IndexError_(
            f"找不到 {readme}。\n"
            f"修正方法：确认仓库根存在 README.md；索引区块需要写在其中。"
        )

    text = readme.read_text(encoding="utf-8")
    block = render_index(entries)

    if INDEX_BEGIN in text and INDEX_END in text:
        pattern = re.compile(
            re.escape(INDEX_BEGIN) + r".*?" + re.escape(INDEX_END),
            flags=re.DOTALL,
        )
        updated = pattern.sub(lambda _: block, text)
    else:
        # 没有标记时在"文章索引"标题后插入，插不进去则追加到文件末尾
        heading = "## 文章索引"
        if heading in text:
            head, _, tail = text.partition(heading)
            updated = f"{head}{heading}\n\n{block}\n{tail}"
        else:
            updated = f"{text.rstrip()}\n\n## 文章索引\n\n{block}\n"

    if updated == text:
        return False, len(entries)

    temp = readme.with_suffix(".md.tmp")
    temp.write_text(updated, encoding="utf-8", newline="\n")
    temp.replace(readme)
    return True, len(entries)


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
