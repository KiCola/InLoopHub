"""命令行入口。

设计约定：

- 命令只做「解析参数 → 调用实现 → 打印结果 → 返回退出码」，业务逻辑不写在这里。
- 未实现的命令**不注册**，避免 ``--help`` 里出现点了没反应的入口（AGENTS.md §3 不谎报）。
- 退出码：成功 0；内容校验失败 1；用法错误由 Typer 负责（2）。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import typer
from rich.console import Console
from rich.markup import escape

from inloop import __version__
from inloop.articles import (
    ARTICLE_FILENAME,
    ArticleCreationError,
    ArticleLocation,
    NewArticleRequest,
    create_article,
    find_articles,
    next_article_id,
)
from inloop.config import ConfigError, load_config, repo_root
from inloop.models.article import Article, ArticleError, Category, Status
from inloop.rules import IssueLevel
from inloop.templates import TemplateError, available_templates, load_template

app = typer.Typer(
    name="inloop",
    help="InLoop 手记：把 Markdown 内容仓库构建为微信公众号文章。",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()
err_console = Console(stderr=True)

#: 内容校验失败时的退出码
EXIT_VALIDATION_FAILED = 1


def _fail(message: str) -> None:
    """以统一格式输出错误并退出。错误信息必须包含修正建议。"""
    err_console.print(f"[bold red]✗[/bold red] {escape(message)}")
    raise typer.Exit(code=EXIT_VALIDATION_FAILED)


def _resolve_article(root: Path, target: str) -> ArticleLocation:
    """把命令行给出的目标解析为文章位置。

    接受三种写法：文章目录、``index.md`` 路径、或 slug（含带序号的目录名）。
    """
    candidate = Path(target)

    # 1) 目录
    for directory in (candidate, root / candidate):
        index = directory / ARTICLE_FILENAME
        if index.is_file():
            return _location_from_index(index, root)

    # 2) 直接指向 index.md
    if candidate.is_file() and candidate.name == ARTICLE_FILENAME:
        return _location_from_index(candidate, root)

    # 3) slug / 目录名
    needle = candidate.name
    for location in find_articles(root):
        if location.slug == needle or location.dir_name == needle:
            return location

    available = ", ".join(loc.dir_name for loc in find_articles(root)) or "（暂无文章）"
    raise ArticleCreationError(
        f"找不到文章：{target}\n"
        f"可用的文章目录：{available}\n"
        "修正方法：传入文章目录（如 articles/2026/001-hello-inloop）"
        "或 slug（如 001-hello-inloop）。"
    )


def _location_from_index(index: Path, root: Path) -> ArticleLocation:
    from inloop.models.article import ARTICLE_DIR_PATTERN

    directory = index.parent
    match = ARTICLE_DIR_PATTERN.match(directory.name)
    return ArticleLocation(
        directory=directory,
        index=index,
        dir_name=directory.name,
        number=int(match.group("number")) if match else None,
        slug=match.group("slug") if match else None,
    )


def _read_article(location: ArticleLocation) -> Article:
    """读取并解析文章，把结构性错误转成 CLI 可展示的失败。"""
    try:
        text = location.index.read_text(encoding="utf-8")
    except OSError as exc:
        _fail(f"无法读取文件 {location.index}：{exc}")
        raise AssertionError("unreachable") from exc  # pragma: no cover

    try:
        return Article.from_text(text, source=location.index)
    except ArticleError as exc:
        _fail(f"{location.index}\n{exc}")
        raise AssertionError("unreachable") from exc  # pragma: no cover


def _relative(path: Path, root: Path) -> str:
    """尽量输出仓库相对路径，便于复制粘贴；不在仓库内时退回绝对路径。"""
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


# --- 基础命令 -------------------------------------------------------------


@app.command()
def version() -> None:
    """显示版本号。"""
    console.print(f"inloop {__version__}")


@app.command()
def info() -> None:
    """显示当前生效的仓库根与配置概要，用于排查「读到的配置对不对」。"""
    try:
        config = load_config()
    except ConfigError as exc:
        _fail(str(exc))
        return

    console.print("[bold]仓库根[/bold]")
    console.print(f"  {config.root}")

    console.print("[bold]站点[/bold]")
    console.print(f"  名称：{config.site_value('name')}")
    console.print(f"  作者：{config.site_value('author')}")
    console.print("[bold]品牌[/bold]")
    console.print(f"  主色：{config.brand_value('primary')}")
    console.print("[bold]微信渲染[/bold]")
    console.print(f"  正文字号：{config.wechat_value('font_size')}px")
    console.print(f"  行高：{config.wechat_value('line_height')}")
    console.print(f"  标题样式：{config.wechat_value('heading_style')}")

    locations = find_articles(config.root)
    console.print("[bold]文章[/bold]")
    console.print(f"  已有 {len(locations)} 篇，下一个编号 {next_article_id(config.root):03d}")
    console.print("[bold]模板[/bold]")
    templates = available_templates(config.root)
    console.print(f"  {', '.join(templates) if templates else '（无）'}")


@app.command()
def root() -> None:
    """只输出仓库根路径，便于脚本与其他工具复用。"""
    try:
        console.print(str(repo_root()))
    except ConfigError as exc:
        _fail(str(exc))


# --- new ------------------------------------------------------------------


@app.command()
def new(
    title: str = typer.Option(None, "--title", "-t", help="文章标题"),
    slug: str = typer.Option(None, "--slug", "-s", help="英文短名，只用小写字母、数字与连字符"),
    category: str = typer.Option(
        None, "--category", "-c", help="栏目：paper/code/build/research/diary"
    ),
    year: int = typer.Option(None, "--year", "-y", help="年份，用于目录分年"),
    template: str = typer.Option(None, "--template", help="模板名，见 --list"),
    tags: str = typer.Option(None, "--tags", help="标签，逗号分隔"),
    summary: str = typer.Option(None, "--summary", help="摘要，一句话"),
    author: str = typer.Option(None, "--author", help="作者，默认取 config/site.yaml"),
    list_templates: bool = typer.Option(False, "--list", help="只列出可用模板后退出"),
    yes: bool = typer.Option(False, "--yes", help="不询问，缺失项用默认值补齐"),
) -> None:
    """新建一篇文章（任务书 §7.1）。"""
    try:
        config = load_config()
    except ConfigError as exc:
        _fail(str(exc))
        return
    root = config.root

    if list_templates:
        _print_templates(root)
        return

    need_prompt = title is None or slug is None or template is None

    # 非交互模式但缺关键项：直接报错，不要静默用默认值蒙混
    if not need_prompt and yes:
        pass
    elif need_prompt and not yes and not _is_interactive():
        _fail(
            "当前环境不是交互式终端，无法询问缺失的字段。\n"
            "修正方法：用参数补全后再执行，例如\n"
            "  inloop new --title \"标题\" --slug light-o1 --template paper-note "
            "--category paper\n"
            "或加 --yes 用默认值补齐。"
        )
        return

    try:
        values = _collect_new_values(
            root=root,
            title=title,
            slug=slug,
            category=category,
            year=year,
            template=template,
            tags=tags,
            summary=summary,
            author=author,
            interactive=(not yes) and need_prompt,
        )
    except ArticleCreationError as exc:
        _fail(str(exc))
        return

    request = NewArticleRequest(
        title=values["title"],
        slug=values["slug"],
        category=values["category"],
        year=values["year"],
        template=values["template"],
        author=values["author"],
        tags=values["tags"],
        summary=values["summary"],
    )

    try:
        result = create_article(root, request)
    except (ArticleCreationError, TemplateError) as exc:
        _fail(str(exc))
        return

    console.print(
        f"[bold green]✓[/bold green] 已创建 {_relative(result.location.directory, root)}"
    )
    console.print(f"  编号：{result.article.id:03d}")
    console.print(f"  模板：{result.template.name}")
    console.print(f"  栏目：{result.article.category.value}（{result.article.category.label}）")
    console.print(f"  正文：{_relative(result.location.index, root)}")
    if (result.location.directory / result.article.cover).is_file():
        console.print(f"  封面：{result.article.cover}（占位图，请替换为真实封面）")
    if result.article.issues:
        console.print("  提示：")
        for issue in result.article.issues:
            console.print(f"    {escape(issue.render())}")


def _is_interactive() -> bool:
    """判断当前是否处于可交互终端。"""
    import sys

    return sys.stdin is not None and sys.stdin.isatty()


def _print_templates(root: Path) -> None:
    names = available_templates(root)
    if not names:
        console.print("（templates/ 下没有可用模板）")
        return
    console.print("[bold]可用模板[/bold]")
    for name in names:
        try:
            template = load_template(root, name)
        except TemplateError as exc:
            console.print(f"  [red]{name}[/red] 无法读取：{exc}")
            continue
        console.print(
            f"  [bold]{name}[/bold]  栏目 {template.category.value}  "
            f"{template.description}"
        )


def _collect_new_values(
    *,
    root: Path,
    title: str | None,
    slug: str | None,
    category: str | None,
    year: int | None,
    template: str | None,
    tags: str | None,
    summary: str | None,
    author: str | None,
    interactive: bool,
) -> dict[str, object]:
    """收集新建文章所需取值，必要时交互询问。"""
    config = load_config(root)
    names = available_templates(root)
    if not names:
        raise ArticleCreationError(
            "templates/ 下没有可用模板，无法新建文章。\n"
            "修正方法：确认仓库内 templates/ 目录存在且含 *.md 模板文件。"
        )

    resolved_title = title
    resolved_slug = slug
    resolved_template = template
    resolved_category = category
    resolved_year = year

    if interactive and resolved_template is None:
        _print_templates(root)
        resolved_template = typer.prompt("模板", default="article")

    if resolved_template is None:
        resolved_template = "article"
    if resolved_template not in names:
        raise ArticleCreationError(
            f"未知模板：{resolved_template}\n"
            f"可用模板：{', '.join(names)}\n"
            "修正方法：用 `inloop new --list` 查看可用模板。"
        )

    # 模板自带的栏目作为默认值
    template_meta = load_template(root, resolved_template)
    if resolved_category is None:
        if interactive:
            resolved_category = typer.prompt(
                "栏目", default=template_meta.category.value
            )
        else:
            resolved_category = template_meta.category.value
    parsed_category = _parse_category_value(resolved_category)

    if interactive and resolved_title is None:
        resolved_title = typer.prompt("标题")
    if resolved_title is None:
        raise ArticleCreationError(
            "缺少标题。\n修正方法：用 --title 提供，或去掉 --yes 进入交互模式。"
        )

    if interactive and resolved_slug is None:
        default_slug = _slugify(resolved_title)
        resolved_slug = typer.prompt("slug（英文短名）", default=default_slug)
    if resolved_slug is None:
        resolved_slug = _slugify(resolved_title)

    if resolved_year is None:
        if interactive:
            resolved_year = typer.prompt("年份", default=str(date.today().year), type=int)
        else:
            resolved_year = date.today().year

    resolved_author = author or str(config.site_value("author"))

    parsed_tags: tuple[str, ...] = ()
    if tags is not None:
        parsed_tags = tuple(part.strip() for part in tags.split(",") if part.strip())
    elif interactive and not summary:
        raw = typer.prompt("标签（逗号分隔，可留空）", default="")
        parsed_tags = tuple(part.strip() for part in raw.split(",") if part.strip())

    resolved_summary = summary
    if resolved_summary is None and interactive:
        resolved_summary = typer.prompt("摘要（一句话，可留空）", default="")

    return {
        "title": resolved_title,
        "slug": str(resolved_slug),
        "category": parsed_category,
        "year": int(resolved_year),
        "template": resolved_template,
        "author": resolved_author,
        "tags": parsed_tags,
        "summary": resolved_summary or "",
    }


def _parse_category_value(value: str) -> Category:
    try:
        return Category(value.strip())
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Category)
        raise ArticleCreationError(
            f"category 取值不合法：`{value}`。允许的取值为：{allowed}（任务书 §16）。"
        ) from exc


def _slugify(text: str) -> str:
    """从标题推导一个 slug 建议值。

    中文标题推导不出有意义的英文短名，此时给出一个显式占位而非空字符串，
    让使用者看到「这里需要你填」而不是悄悄生成一个 `untitled`。
    """
    import re

    lowered = text.strip().lower()
    ascii_part = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
    ascii_part = re.sub(r"-{2,}", "-", ascii_part)
    return ascii_part or "todo-slug"


# --- check ----------------------------------------------------------------


@app.command()
def check(
    target: str = typer.Argument(..., help="文章目录、index.md 路径或 slug"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="没有问题时也保持安静"),
) -> None:
    """检查一篇文章（任务书 §7.2）。"""
    try:
        config = load_config()
    except ConfigError as exc:
        _fail(str(exc))
        return

    root = config.root
    try:
        location = _resolve_article(root, target)
    except ArticleCreationError as exc:
        _fail(str(exc))
        return

    try:
        article = Article.from_text(
            location.index.read_text(encoding="utf-8"), source=location.index
        )
    except ArticleError as exc:
        err_console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        console.print(f"{_relative(location.index, root)} ERROR 结构错误")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED) from exc

    if not article.issues:
        if not quiet:
            console.print(
                f"[bold green]✓[/bold green] {_relative(location.index, root)} "
                f"PASS（{article.id:03d} {article.title}）"
            )
        return

    for issue in article.issues:
        style = "red" if issue.level is IssueLevel.ERROR else "yellow"
        console.print(f"[{style}]{escape(issue.render(location.index))}[/{style}]")

    error_count = len(article.errors)
    warning_count = len(article.warnings)
    summary_line = (
        f"{_relative(location.index, root)}  汇总："
        f"ERROR {error_count} / WARNING {warning_count}"
    )
    if error_count:
        console.print(f"[bold red]{escape(summary_line)}[/bold red]")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED)
    console.print(f"[bold yellow]{escape(summary_line)}[/bold yellow]")


@app.command()
def rules() -> None:
    """列出全部校验规则码，便于对照报错。"""
    from inloop.rules import ALL_RULES

    console.print("[bold]规则码[/bold]")
    for rule in ALL_RULES:
        style = "red" if rule.level is IssueLevel.ERROR else "yellow"
        console.print(f"  {rule.code}  [{style}]{rule.level.value:7s}[/{style}] {rule.summary}")


# --- 状态 ----------------------------------------------------------------

_STATUS_HINT = "  ".join(item.value for item in Status)


@app.command()
def status(
    target: str = typer.Argument(..., help="文章目录、index.md 路径或 slug"),
    new_status: str = typer.Argument(..., help=f"新状态，取值：{_STATUS_HINT}"),
) -> None:
    """修改文章的 status 字段（任务书 §17）。

    这是**唯一**允许程序改写已存在文章文件的场景，且改动范围仅限 status 一行。
    """
    try:
        config = load_config()
    except ConfigError as exc:
        _fail(str(exc))
        return

    root = config.root
    try:
        location = _resolve_article(root, target)
    except ArticleCreationError as exc:
        _fail(str(exc))
        return

    raw_status = new_status.strip()
    allowed = ", ".join(item.value for item in Status)
    try:
        want = Status(raw_status)
    except ValueError:
        _fail(
            f"status 取值不合法：`{new_status}`。允许的取值为：{allowed}（任务书 §4）。"
        )
        return

    original = location.index.read_text(encoding="utf-8")
    updated, changed = _replace_status_line(original, want.value)
    if not changed:
        _fail(
            f"在 {_relative(location.index, root)} 中未找到 `status:` 行，无法修改。\n"
            "修正方法：确认 front matter 中含 status 字段。"
        )
        return

    article = Article.from_text(updated, source=location.index)
    if not article.is_valid:
        for issue in article.errors:
            err_console.print(f"[red]{escape(issue.render(location.index))}[/red]")
        _fail("修改后文章存在 ERROR，已放弃写入，源文件未变。")

    location.index.write_text(updated, encoding="utf-8", newline="\n")
    console.print(
        f"[bold green]✓[/bold green] {_relative(location.index, root)} "
        f"status → {want.value}"
    )


def _replace_status_line(text: str, new_value: str) -> tuple[str, bool]:
    """只替换 front matter 内的 status 行，其余内容原样保留。"""
    lines = text.replace("\r\n", "\n").split("\n")
    if not lines or lines[0].strip() != "---":
        return text, False

    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            break
        if lines[index].lstrip().startswith("status:"):
            indent = lines[index][: len(lines[index]) - len(lines[index].lstrip())]
            lines[index] = f"{indent}status: {new_value}"
            return "\n".join(lines), True
    return text, False


if __name__ == "__main__":  # pragma: no cover - 手动调试用
    app()
