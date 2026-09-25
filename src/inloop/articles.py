"""文章的扫描、编号分配与新建。

职责边界：

- **负责**：在 ``articles/`` 下发现文章、分配新编号、新建文章目录与文件。
- **不负责**：front matter 的语义（在 :mod:`inloop.models.article`）、
  模板填充细节（在 :mod:`inloop.templates`）、命令行交互（在 :mod:`inloop.cli`）。

编号策略：``id`` 在**整个仓库范围内唯一且递增**，不按年份重置。这样它能作为
稳定的排序键，也不会因为换年出现重复编号。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from inloop.models.article import (
    ARTICLE_DIR_PATTERN,
    SLUG_PATTERN,
    Article,
    Category,
    Status,
)
from inloop.models.serializer import write_article
from inloop.templates import Template, load_template, render_template_text

#: 文章根目录名（相对仓库根）
ARTICLES_DIR = "articles"

#: 文章正文文件名
ARTICLE_FILENAME = "index.md"

#: 封面默认文件名
COVER_FILENAME = "cover.png"


class ArticleCreationError(ValueError):
    """文章无法创建（目录已存在、模板缺失、取值非法等）。"""


@dataclass(frozen=True, slots=True)
class ArticleLocation:
    """一篇文章在仓库中的位置。"""

    #: 文章目录
    directory: Path
    #: 正文文件
    index: Path
    #: 目录名，形如 ``002-light-o1``
    dir_name: str
    #: 从目录名解析出的编号；目录名不含编号时为 None
    number: int | None
    #: 从目录名解析出的 slug；目录名不符合约定时为 None
    slug: str | None


@dataclass(frozen=True, slots=True)
class NewArticleRequest:
    """新建文章的输入。

    Attributes:
        title: 标题。
        slug: 英文短名。
        category: 栏目。
        year: 年份，用于目录分年。
        template: 模板名。
        author: 作者。
        tags: 标签。
        summary: 摘要。
        status: 初始状态；为 None 时取模板的 ``default_status``。
        cover: 封面文件名。
    """

    title: str
    slug: str
    category: Category
    year: int
    template: str
    author: str
    tags: tuple[str, ...] = ()
    summary: str = ""
    status: Status | None = None
    cover: str = COVER_FILENAME


@dataclass(frozen=True, slots=True)
class NewArticleResult:
    """新建文章的结果。"""

    article: Article
    location: ArticleLocation
    template: Template


# --- 扫描与编号 -----------------------------------------------------------


def articles_root(root: Path) -> Path:
    """返回文章根目录。"""
    return root / ARTICLES_DIR


def find_articles(root: Path) -> tuple[ArticleLocation, ...]:
    """扫描 ``articles/``，返回全部文章位置，按编号排序。

    只认含 ``index.md`` 的**两级**目录（``articles/<年份>/<文章>/``），
    与任务书 §3 的结构一致。编号为 None 的目录排在最后。
    """
    base = articles_root(root)
    if not base.is_dir():
        return ()

    found: list[ArticleLocation] = []
    for year_dir in sorted(p for p in base.iterdir() if p.is_dir()):
        for article_dir in sorted(p for p in year_dir.iterdir() if p.is_dir()):
            index = article_dir / ARTICLE_FILENAME
            if not index.is_file():
                continue
            match = ARTICLE_DIR_PATTERN.match(article_dir.name)
            found.append(
                ArticleLocation(
                    directory=article_dir,
                    index=index,
                    dir_name=article_dir.name,
                    number=int(match.group("number")) if match else None,
                    slug=match.group("slug") if match else None,
                )
            )

    # 有编号的按编号排序，无编号的按路径排序排在后面
    found.sort(key=lambda loc: (loc.number is None, loc.number or 0, str(loc.directory)))
    return tuple(found)


def next_article_id(root: Path) -> int:
    """计算下一个可用编号。

    以「已有最大编号 + 1」为准，而不是「文章数量 + 1」——删掉中间某篇后
    再新建，不会复用已用过的编号。
    """
    numbers = [loc.number for loc in find_articles(root) if loc.number is not None]
    return max(numbers) + 1 if numbers else 1


def find_by_slug(root: Path, slug: str) -> ArticleLocation | None:
    """按 slug 查找文章目录。"""
    for location in find_articles(root):
        if location.slug == slug or location.dir_name == slug:
            return location
    return None


# --- 新建 -----------------------------------------------------------------


def create_article(
    root: Path,
    request: NewArticleRequest,
    *,
    make_cover: bool = True,
) -> NewArticleResult:
    """在仓库中新建一篇文章。

    Args:
        root: 仓库根。
        request: 新建参数。
        make_cover: 是否生成封面占位图。

    Returns:
        新建结果。

    Raises:
        ArticleCreationError: 取值非法、模板缺失或目标目录已存在。
    """
    slug = request.slug.strip()
    if not slug:
        raise ArticleCreationError(
            "slug 不能为空。\n"
            "修正方法：提供一个英文短名，只含小写字母、数字与连字符，例如 `light-o1`。"
        )
    if not SLUG_PATTERN.match(slug):
        raise ArticleCreationError(
            f"slug 格式不合法：`{slug}`。\n"
            "修正方法：只使用小写字母、数字与连字符，不能以连字符开头或结尾，"
            "例如 `light-o1`。"
        )

    title = request.title.strip()
    if not title:
        raise ArticleCreationError(
            "标题不能为空。\n修正方法：用 --title 提供标题，或在交互模式下填写。"
        )

    if not request.author.strip():
        raise ArticleCreationError(
            "作者不能为空。\n"
            "修正方法：检查 config/site.yaml 的 `site.author`，或显式提供 --author。"
        )

    # 同 slug 已存在时拒绝，避免出现两篇同名文章导致产物目录互相覆盖
    existing = find_by_slug(root, slug)
    if existing is not None:
        raise ArticleCreationError(
            f"已存在 slug 为 `{slug}` 的文章：{existing.directory}\n"
            "修正方法：换一个 slug，或直接编辑已有文章。"
        )

    template = load_template(root, request.template)
    article_id = next_article_id(root)
    status = request.status or template.default_status
    today = date.today()

    directory = articles_root(root) / str(request.year) / f"{article_id:03d}-{slug}"
    if directory.exists():
        raise ArticleCreationError(
            f"目标目录已存在：{directory}\n"
            "修正方法：换一个 slug，或删除该目录后重试。"
        )

    values = _template_values(
        request=request,
        article_id=article_id,
        slug=slug,
        title=title,
        status=status,
        today=today,
    )
    text = render_template_text(template, values)

    # 模板渲染后再解析，确保写出的文件确实是一篇合法文章
    try:
        article = Article.from_text(text, source=directory / ARTICLE_FILENAME)
    except ValueError as exc:
        raise ArticleCreationError(
            f"模板 `{template.name}` 渲染后无法解析为文章：{exc}\n"
            f"这属于模板自身的缺陷（模板文件：{template.path}）。"
        ) from exc

    # 有 ERROR 就不落盘：留下一个必然构建失败的文章，不如当场报错。
    # 这条同时兜住"模板有缺陷"和"取值不合法"两类情况（AGENTS.md §3 不谎报）。
    if article.errors:
        detail = "\n".join(f"  {issue.render()}" for issue in article.errors)
        raise ArticleCreationError(
            f"新文章未通过校验，已放弃创建（未写入任何文件）：\n{detail}\n"
            "修正方法：检查模板是否完整，以及 --slug / --title 等取值是否合法。"
        )

    directory.mkdir(parents=True, exist_ok=False)
    (directory / "assets").mkdir(exist_ok=True)
    write_article(article, directory / ARTICLE_FILENAME, body=article.body)

    if make_cover:
        write_cover_placeholder(directory / request.cover, title=title, slug=slug)

    location = ArticleLocation(
        directory=directory,
        index=directory / ARTICLE_FILENAME,
        dir_name=directory.name,
        number=article_id,
        slug=slug,
    )
    return NewArticleResult(article=article, location=location, template=template)


def _template_values(
    *,
    request: NewArticleRequest,
    article_id: int,
    slug: str,
    title: str,
    status: Status,
    today: date,
) -> dict[str, str]:
    """构造模板占位符取值。"""
    # tags 占位符需要包含缩进：模板里写作 `tags:\n{{tags}}`
    if request.tags:
        tags_block = "\n".join(f"  - {tag}" for tag in request.tags)
    else:
        tags_block = "  - TODO"
    return {
        "id": str(article_id),
        "title": _escape_yaml_string(title),
        "slug": slug,
        "date": today.isoformat(),
        "year": str(request.year),
        "author": _escape_yaml_string(request.author),
        # 栏目以调用方选择为准；模板元数据里的 category 只用于决定默认值
        "category": str(request.category),
        "status": str(status),
        "tags": tags_block,
        "summary": _escape_yaml_string(request.summary),
        "cover": request.cover,
        "template": request.template,
    }


def _escape_yaml_string(value: str) -> str:
    """把文本放进双引号 YAML 标量中所需的最小转义。

    模板里标题写作 ``title: "{{title}}"``，因此只需处理反斜杠与双引号；
    YAML 双引号标量里这两个字符必须转义。冒号、``#`` 等在双引号内是安全的。
    """
    return value.replace("\\", "\\\\").replace('"', '\\"')


# --- 封面占位图 -----------------------------------------------------------


#: 候选字体：Windows 中文字体优先，其次跨平台常见路径。
_FONT_CANDIDATES: tuple[str, ...] = (
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyh.ttf",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
    "/System/Library/Fonts/PingFang.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc",
)

#: 封面比例 2.35:1（微信公众号封面规格）
COVER_SIZE = (1175, 500)

#: 品牌主色克莱茵蓝，与 config/site.yaml 的 brand.primary 一致
COVER_BACKGROUND = (0, 47, 167)
COVER_TEXT_COLOR = (255, 255, 255)


def find_cover_font() -> Path | None:
    """查找可用的中文字体文件。找不到时返回 None（调用方降级为纯色块）。"""
    for candidate in _FONT_CANDIDATES:
        path = Path(candidate)
        if path.is_file():
            return path
    return None


def write_cover_placeholder(path: Path, *, title: str, slug: str) -> bool:
    """生成封面占位图。

    有中文字体时绘制标题，否则画纯色块。**不抛异常**：封面只是占位，
    生成失败不应该让整个新建流程失败，但会返回 False 让调用方提示。

    Returns:
        是否成功写出文件。
    """
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError:  # pragma: no cover - Pillow 是必需依赖
        return False

    try:
        image = Image.new("RGB", COVER_SIZE, COVER_BACKGROUND)
        draw = ImageDraw.Draw(image)

        font_path = find_cover_font()
        if font_path is not None:
            # 依封面高度选字号，并允许标题换行成多行
            font = ImageFont.truetype(str(font_path), 64)
            lines = _wrap_for_cover(title, max_chars=16)
            line_height = 84
            total_height = line_height * len(lines)
            y = (COVER_SIZE[1] - total_height) // 2
            for line in lines:
                width = draw.textlength(line, font=font)
                draw.text(((COVER_SIZE[0] - width) / 2, y), line, font=font, fill=COVER_TEXT_COLOR)
                y += line_height

        path.parent.mkdir(parents=True, exist_ok=True)
        image.save(path, format="PNG", optimize=True)
        return True
    except OSError:
        # 例如磁盘满、路径非法；属于可恢复问题，由调用方决定如何提示
        return False


def _wrap_for_cover(text: str, max_chars: int) -> list[str]:
    """按字数粗略折行；中文按字符断行即可，不引入分词依赖。"""
    cleaned = re.sub(r"\s+", " ", text).strip()
    if not cleaned:
        return []
    return [cleaned[i : i + max_chars] for i in range(0, len(cleaned), max_chars)]
