"""命令行入口。

设计约定：

- 命令只做「解析参数 → 调用实现 → 打印结果 → 返回退出码」，业务逻辑不写在这里。
- 未实现的命令**不注册**，避免 ``--help`` 里出现点了没反应的入口（AGENTS.md §3 不谎报）。
- 退出码：成功 0；内容校验失败 1；用法错误由 Typer 负责（2）。

**两个根**（任务书 §3）：``content_root`` 放文章、``repo_root`` 放工具。
全局参数 ``--content`` 可临时指定内容目录；不传时按
``INLOOP_CONTENT`` → 配置 → 兜底 的顺序解析（见 :meth:`Config.resolve_content_root`）。
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.markup import escape

from inloop import __version__
from inloop.articles import (
    ArticleCreationError,
    ArticleDeletionError,
    ArticleLocation,
    ArticleNotFoundError,
    NewArticleRequest,
    create_article,
    delete_article,
    find_articles,
    next_article_id,
    resolve_article,
)
from inloop.config import Config, ConfigError, load_config, repo_root
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

#: 全局参数 ``--content`` 的存放位置（由 :func:`main_callback` 写入）。
#: 用模块级变量而不是 Context 对象：命令实现里到处都要取内容目录，
#: 每次穿透 ctx.obj 会让签名变吵，而这是一个"进程级"设置。
_content_override: Path | None = None
_json_mode: bool = False


def _config_or_fail() -> Config:
    """加载配置，失败即退出。"""
    try:
        return load_config()
    except ConfigError as exc:
        _fail(str(exc), code=exc.code)
        raise AssertionError("unreachable") from exc  # pragma: no cover


def _content_root_or_fail(config: Config) -> Path:
    """解析内容目录，失败即退出。

    内容目录是**所有文章相关命令的前提**：解析不出来就没有可操作的对象，
    因此这里直接失败并说明四种来源，而不是悄悄回退到某个目录。

    错误码沿用 :class:`ConfigError` 的 ``code``：插件需要据此区分
    "内容目录没配好（应引导去设置界面）"与"意外故障"。
    """
    try:
        return config.resolve_content_root(_content_override)
    except ConfigError as exc:
        _fail(str(exc), code=exc.code)
        raise AssertionError("unreachable") from exc  # pragma: no cover


@app.callback()
def main_callback(
    ctx: typer.Context,
    content: Annotated[
        Path | None,
        typer.Option(
            "--content",
            help="内容目录（放文章的地方）。默认按 INLOOP_CONTENT 环境变量、"
            "再按 config/site.yaml 的 content.root，最后回退到仓库内的 articles/。",
        ),
    ] = None,
    as_json: Annotated[
        bool,
        typer.Option(
            "--json",
            help="输出机器可读的 JSON（供编辑器插件等外部程序调用）。"
            "stdout 只含 JSON，人类可读的提示走 stderr。",
        ),
    ] = False,
) -> None:
    """InLoop 手记：把 Markdown 内容仓库构建为微信公众号文章。"""
    global _content_override, _json_mode  # noqa: PLW0603 - 进程级设置，见上方说明
    _content_override = content
    _json_mode = as_json
    ctx.obj = {"content": content, "json": as_json}


def _json_output() -> bool:
    """当前是否处于 JSON 输出模式。"""
    return _json_mode


def _fail(message: str, *, code: str = "command_failed", hint: str = "") -> None:
    """以统一格式输出错误并退出。错误信息必须包含修正建议。

    JSON 模式下仍在 **stdout** 输出一份合法 JSON：调用方不必解析 stderr 的文本，
    只要看 ``ok: false`` 与 ``error.code``。退出码依旧非 0。

    **这是错误输出的唯一出口。** 调用点不要再单独调用 ``jsonapi.emit_error``——
    两处都发会把两份 JSON 写进 stdout，调用方 ``json.loads`` 直接失败
    （这个 bug 真出现过）。
    """
    if _json_output():
        from inloop import jsonapi

        jsonapi.emit_error(code, message, hint=hint)
    err_console.print(f"[bold red]✗[/bold red] {escape(message)}")
    raise typer.Exit(code=EXIT_VALIDATION_FAILED)


def _out(message: str) -> None:
    """打印人类可读信息。

    JSON 模式下改走 stderr：stdout 必须留给 JSON，
    否则调用方 ``json.loads(stdout)`` 会失败。
    """
    target = err_console if _json_output() else console
    target.print(message)


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


def _relative(path: Path, base: Path) -> str:
    """输出相对 ``base`` 的路径，便于阅读与复制粘贴；算不出时退回绝对路径。

    仅用于**展示**。产物里的路径绝不能走这个回退——那边必须报错，
    见 :func:`inloop.build._relative_reference`。
    """
    try:
        return path.relative_to(base).as_posix()
    except ValueError:
        return str(path)


def _display_path(path: Path, config: Config, content_root: Path) -> str:
    """展示路径时优先给"相对内容目录"的形式。

    文章与工具分处两个根，因此不能一律相对仓库根：文章在内容目录下，
    相对仓库根算出来的会是 ``../../Users/...`` 这种没法看的东西。
    """
    for base in (content_root, config.root):
        try:
            return path.relative_to(base).as_posix()
        except ValueError:
            continue
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

    console.print("[bold]工具仓库根[/bold]")
    console.print(f"  {config.root}")

    # 内容目录是**最容易搞错**的一项：它有四个来源，配错了会让命令读到另一个目录。
    # 因此不仅打印解析结果，还打印它来自哪里。
    content_root = _content_root_or_fail(config)
    console.print("[bold]内容目录[/bold]")
    console.print(f"  {content_root}")
    console.print(f"  [dim]来源：{_content_root_source(config)}[/dim]")

    console.print("[bold]构建产物目录[/bold]")
    console.print(f"  {config.resolve_dist_root()}")

    console.print("[bold]站点[/bold]")
    console.print(f"  名称：{config.site_value('name')}")
    console.print(f"  作者：{config.site_value('author')}")
    console.print("[bold]品牌[/bold]")
    console.print(f"  主色：{config.brand_value('primary')}")
    console.print("[bold]微信渲染[/bold]")
    console.print(f"  正文字号：{config.wechat_value('font_size')}px")
    console.print(f"  行高：{config.wechat_value('line_height')}")
    console.print(f"  标题样式：{config.wechat_value('heading_style')}")

    locations = find_articles(content_root)
    console.print("[bold]文章[/bold]")
    console.print(f"  已有 {len(locations)} 篇，下一个编号 {next_article_id(content_root):03d}")
    console.print("[bold]模板[/bold]")
    templates = available_templates(config.root)
    console.print(f"  {', '.join(templates) if templates else '（无）'}")


def _content_root_source(config: Config) -> str:
    """说明内容目录是从哪一级解析出来的。"""
    import os

    if _content_override is not None:
        return "命令行参数 --content"
    if os.environ.get("INLOOP_CONTENT", "").strip():
        return "环境变量 INLOOP_CONTENT"
    if str(config.content.get("root") or "").strip():
        return "config/site.yaml 的 content.root"
    return "兜底（工具仓库内的 articles/）"


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
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)
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
            repo_root=root,
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
        result = create_article(content_root, root, request)
    except (ArticleCreationError, TemplateError) as exc:
        _fail(str(exc))
        return

    console.print(
        f"[bold green]✓[/bold green] 已创建 "
        f"{_display_path(result.location.directory, config, content_root)}"
    )
    console.print(f"  编号：{result.article.id:03d}")
    console.print(f"  模板：{result.template.name}")
    console.print(f"  栏目：{result.article.category.value}（{result.article.category.label}）")
    console.print(f"  正文：{_display_path(result.location.index, config, content_root)}")
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


def _confirm(question: str, *, default: bool = False) -> bool:
    """就一个破坏性操作征求确认。

    非交互环境（管道、脚本、CI）下**一律返回 False**：没人能回答的提问
    不能当成"同意"，那等于把危险操作变成静默执行。
    """
    if not _is_interactive():
        err_console.print(
            "[bold yellow]当前不是交互式终端，无法征求确认，已取消。[/bold yellow]"
        )
        err_console.print("  确定要执行时请显式加上 `--yes`。")
        return False

    import typer as _typer

    prompt = f"{question} [y/N]" if not default else f"{question} [Y/n]"
    try:
        return bool(_typer.prompt(prompt, default="y" if default else "n").lower().startswith("y"))
    except (EOFError, KeyboardInterrupt):
        # 用户中断提问：视为拒绝，而不是让异常冒到顶层变成"程序崩了"
        console.print()
        return False


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
    repo_root: Path,
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
    """收集新建文章所需取值，必要时交互询问。

    参数是**工具仓库根**而非内容目录：配置、模板、站点信息都属于工具，
    与文章存放位置无关。
    """
    config = load_config(repo_root)
    names = available_templates(repo_root)
    if not names:
        raise ArticleCreationError(
            "templates/ 下没有可用模板，无法新建文章。\n"
            "修正方法：确认工具仓库内 templates/ 目录存在且含 *.md 模板文件。"
        )

    resolved_title = title
    resolved_slug = slug
    resolved_template = template
    resolved_category = category
    resolved_year = year

    if interactive and resolved_template is None:
        _print_templates(repo_root)
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
    template_meta = load_template(repo_root, resolved_template)
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
    target: str = typer.Argument(None, help="文章目录、index.md 路径或 slug；配合 --all 可省略"),
    quiet: bool = typer.Option(False, "--quiet", "-q", help="没有问题时也保持安静"),
    all_articles: bool = typer.Option(
        False, "--all", help="检查内容目录里的**全部**文章，而不是单篇"
    ),
) -> None:
    """检查文章（任务书 §7.2）。

    默认检查一篇；``--all`` 检查内容目录里的全部文章——
    工具自带的示例文章覆盖不到作者的真实内容，写完一批后用它统一过一遍。
    """
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)

    if all_articles:
        _check_all(config, content_root, quiet=quiet)
        return

    if not target:
        _fail(
            "缺少要检查的文章。\n"
            "修正方法：传入 slug（如 `002-light-o1`），"
            "或用 `inloop check --all` 检查全部文章。"
        )
        return

    try:
        location = resolve_article(content_root, target)
    except ArticleNotFoundError as exc:
        _fail(str(exc), code="article_not_found", hint="用 `inloop list` 查看可用文章。")
        return

    try:
        article = Article.from_text(
            location.index.read_text(encoding="utf-8"), source=location.index
        )
    except ArticleError as exc:
        _fail(
            f"{_display_path(location.index, config, content_root)} 结构错误：{exc}",
            code="article_unparsable",
            hint="检查该文件的 Front Matter（两行 --- 之间）与正文结构。",
        )
        return

    if _json_output():
        from inloop import jsonapi

        jsonapi.emit(jsonapi.check_payload(article, location, base=content_root))
        if article.errors:
            raise typer.Exit(code=EXIT_VALIDATION_FAILED)
        return

    _report_one(article, location, config, content_root, quiet=quiet)


def _check_all(config: Config, content_root: Path, *, quiet: bool) -> None:
    """检查内容目录里的全部文章（任务书 §7.5 支持 --json）。

    用途：工具自带的示例文章覆盖不到作者的真实内容，因此需要一条
    "把我所有文章过一遍"的命令。**空目录不算通过**——没有文章就无从谈起
    "检查通过"，那会给出虚假的安心感。
    """
    from inloop import jsonapi

    locations = find_articles(content_root)
    if not locations:
        _fail(
            f"内容目录里没有文章：{content_root}\n"
            f"修正方法：确认内容目录是否正确（用 `inloop info` 查看来源），"
            f"或先用 `inloop new` 新建一篇。"
        )
        return

    if not _json_output():
        console.print(f"[bold]检查 {len(locations)} 篇文章[/bold]")
        console.print(f"  内容目录：{content_root}")
        console.print()

    errors = 0
    warnings = 0
    unparsable = 0
    items: list[dict] = []
    for location in locations:
        try:
            article = Article.from_text(
                location.index.read_text(encoding="utf-8"), source=location.index
            )
        except (ArticleError, OSError) as exc:
            unparsable += 1
            errors += 1
            if _json_output():
                items.append(
                    jsonapi.unparsable_to_dict(
                        location, base=content_root, reason=str(exc)
                    )
                )
            err_console.print(
                f"[bold red]✗[/bold red] {_display_path(location.index, config, content_root)}"
                f" 结构错误：{escape(str(exc))}"
            )
            continue

        if _json_output():
            items.append(jsonapi.article_to_dict(article, location, base=content_root))
            errors += len(article.errors)
            warnings += len(article.warnings)
            continue

        count = _report_one(article, location, config, content_root, quiet=quiet)
        errors += count[0]
        warnings += count[1]

    if _json_output():
        jsonapi.emit(
            jsonapi.check_all_payload(
                items,
                content_root=content_root,
                error_count=errors,
                warning_count=warnings,
                unparsable=unparsable,
            )
        )
        if errors:
            raise typer.Exit(code=EXIT_VALIDATION_FAILED)
        return

    console.print()
    summary = (
        f"汇总：{len(locations)} 篇  ERROR {errors} / WARNING {warnings}"
        + (f"（{unparsable} 篇无法解析）" if unparsable else "")
    )
    if errors:
        console.print(f"[bold red]{escape(summary)}[/bold red]")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED)
    console.print(f"[bold green]{escape(summary)}[/bold green]")


def _report_one(
    article: Article,
    location: ArticleLocation,
    config: Config,
    content_root: Path,
    *,
    quiet: bool,
) -> tuple[int, int]:
    """打印一篇文章的校验结果。

    Returns:
        ``(ERROR 数, WARNING 数)``。不抛异常——由调用方决定是"单篇失败即退出"
        还是"累计到最后统一汇报"。
    """
    shown = _display_path(location.index, config, content_root)
    if not article.issues:
        if not quiet:
            console.print(
                f"[bold green]✓[/bold green] {shown} PASS（{article.id:03d} {article.title}）"
            )
        return 0, 0

    for issue in article.issues:
        style = "red" if issue.level is IssueLevel.ERROR else "yellow"
        console.print(f"[{style}]{escape(issue.render(location.index))}[/{style}]")

    error_count = len(article.errors)
    warning_count = len(article.warnings)
    summary_line = f"{shown}  汇总：ERROR {error_count} / WARNING {warning_count}"
    if error_count:
        console.print(f"[bold red]{escape(summary_line)}[/bold red]")
    else:
        console.print(f"[bold yellow]{escape(summary_line)}[/bold yellow]")
    return error_count, warning_count


@app.command()
def rules() -> None:
    """列出全部校验规则码，便于对照报错。"""
    from inloop.rules import ALL_RULES

    console.print("[bold]规则码[/bold]")
    for rule in ALL_RULES:
        style = "red" if rule.level is IssueLevel.ERROR else "yellow"
        console.print(f"  {rule.code}  [{style}]{rule.level.value:7s}[/{style}] {rule.summary}")


# --- build-wechat / preview-wechat ---------------------------------------


@app.command("build-wechat")
def build_wechat(
    target: str = typer.Argument(..., help="文章目录、index.md 路径或 slug"),
    theme: str = typer.Option(
        None, "--theme", help="排版主题，见 `inloop themes`；默认取 config/wechat.yaml"
    ),
) -> None:
    """构建微信公众号产物（任务书 §8）。"""
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)
    location, article = _load_article_or_fail(config, content_root, target)

    from inloop.build import BuildError, build_article

    try:
        outcome = build_article(
            article, config=config, content_root=content_root, theme=theme
        )
    except BuildError as exc:
        _fail(
            str(exc),
            code="build_failed",
            hint="先运行 `inloop check <slug>` 定位内容问题。",
        )
        return

    if _json_output():
        from inloop import jsonapi

        jsonapi.emit(jsonapi.build_payload(outcome, content_root=content_root))
        # 警告仍走 stderr，便于人类看到而污染不到 stdout
        _print_warnings(outcome.warnings)
        return

    console.print(
        f"[bold green]✓[/bold green] 构建完成 "
        f"{_relative(outcome.output_dir, config.root)}"
    )
    for relative in outcome.files:
        full = outcome.output_dir / relative
        size = full.stat().st_size if full.exists() else 0
        console.print(f"  {relative.as_posix():28s} {_human_size(size)}")

    _print_publish_checklist(outcome.metadata, config.root)
    _print_warnings(outcome.warnings)


def _print_publish_checklist(metadata: dict[str, object], root: Path) -> None:
    """打印"照这个顺序插图"的清单。

    为什么需要它：实测微信编辑器**不会**抓取正文里的本地图片路径，也不会抓外链，
    正文图片只能在编辑器里逐张手动上传。只给一堆文件名，人无法判断该插在哪一节之后，
    因此这里按正文出现顺序列出序号、文件名与所属章节。
    """
    raw_images = metadata.get("images")
    if not isinstance(raw_images, list) or not raw_images:
        return

    body = [
        entry
        for entry in raw_images
        if isinstance(entry, dict) and entry.get("kind") == "body"
    ]
    covers = [
        entry
        for entry in raw_images
        if isinstance(entry, dict) and entry.get("kind") == "cover"
    ]

    console.print()
    console.print("[bold]发布清单[/bold]")
    if body:
        console.print("  正文图片（按顺序在编辑器里上传）：")
        for entry in body:
            section = str(entry.get("section") or "").strip()
            where = f"「{section}」一节内" if section else "正文开头处"
            console.print(
                f"    第 {entry.get('order')} 张  {entry.get('output')}"
                f"  → {where}"
            )
    else:
        console.print("  正文没有图片。")

    if covers:
        console.print(f"  封面：{covers[0].get('output')}（在后台单独上传）")

    console.print(
        "  步骤：浏览器打开 article.html → 全选复制 → 后台新建图文 → "
        "可视区粘贴 → 逐张上传上面的图片 → 填标题/作者/摘要 → 手机预览后再发"
    )


@app.command("themes")
def themes() -> None:
    """列出可用的排版主题及其定位。"""
    from inloop.renderer.wechat import theme_name
    from inloop.rendering import describe_themes

    config = _config_or_fail()
    entries = describe_themes(config)
    if not entries:
        console.print("styles/themes/ 下没有主题文件。")
        return

    current = theme_name(config)
    console.print("[bold]可用主题[/bold]")
    for name, purpose in entries:
        mark = " [green]（当前）[/green]" if name == current else ""
        detail = f"  {purpose}" if purpose else ""
        console.print(f"  [bold]{name}[/bold]{mark}{detail}")

    console.print()
    console.print(
        f"切换方式：改 {_relative(config.root / 'config' / 'wechat.yaml', config.root)} "
        f"的 `theme`，或用 `inloop build-wechat <文章> --theme <名称>` 临时指定。"
    )
    themes_readme = _relative(config.root / "styles" / "themes" / "README.md", config.root)
    console.print(f"主题清单与调参入口：{themes_readme}")


@app.command("preview-wechat")
def preview_wechat(
    target: str = typer.Argument(..., help="文章目录、index.md 路径或 slug"),
    port: int = typer.Option(None, "--port", "-p", help="端口，默认 8000 起自动顺延"),
    no_open: bool = typer.Option(False, "--no-open", help="不自动打开浏览器"),
) -> None:
    """构建并启动本地预览服务（任务书 §13）。"""
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)
    location, article = _load_article_or_fail(config, content_root, target)

    from inloop.build import BuildError, build_article
    from inloop.preview import DEFAULT_PORT, PreviewError, find_free_port, serve

    try:
        outcome = build_article(article, config=config, content_root=content_root)
    except BuildError as exc:
        _fail(
            str(exc),
            code="build_failed",
            hint="先运行 `inloop check <slug>` 定位内容问题。",
        )
        return

    console.print(
        f"[bold green]✓[/bold green] 构建完成 {_relative(outcome.output_dir, config.root)}"
    )
    _print_publish_checklist(outcome.metadata, config.root)
    _print_warnings(outcome.warnings)

    try:
        resolved_port = port if port is not None else find_free_port(DEFAULT_PORT)
        serve(
            outcome.output_dir,
            port=resolved_port,
            open_browser=not no_open,
            path=f"/{ARTICLE_PREVIEW_NAME}",
        )
    except PreviewError as exc:
        err_console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED) from exc


# --- index ---------------------------------------------------------------


@app.command()
def index(
    check: bool = typer.Option(
        False, "--check", help="只检查索引是否为最新，不写入"
    ),
    force: bool = typer.Option(
        False, "--force", help="目标文件缺少标记时，用生成的索引整份覆盖它"
    ),
) -> None:
    """生成内容目录下的 INDEX.md 文章索引（任务书 §14）。"""
    from inloop.index import (
        INDEX_FILE_NAME,
        IndexError_,
        check_index_file,
        collect_entries,
        update_index_file,
    )

    config = _config_or_fail()
    content_root = _content_root_or_fail(config)

    try:
        entries = collect_entries(content_root)
    except IndexError_ as exc:
        _fail(str(exc))
        return

    target = _display_path(content_root / INDEX_FILE_NAME, config, content_root)

    if check:
        fresh, detail = check_index_file(content_root, entries)
        if fresh:
            console.print(f"[bold green]✓[/bold green] {target} 已是最新（{len(entries)} 篇）")
            return
        err_console.print(
            f"[bold red]✗[/bold red] {escape(detail or f'{target} 与文章不一致')}"
        )
        console.print("修正方法：运行 `inloop index` 更新索引。")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED)

    try:
        changed, count = update_index_file(
            content_root, entries, allow_create=True, force=force
        )
    except IndexError_ as exc:
        _fail(str(exc))
        return

    if changed:
        console.print(f"[bold green]✓[/bold green] {target} 已更新（{count} 篇）")
    else:
        console.print(f"[bold green]✓[/bold green] {target} 无变化（{count} 篇）")


# --- list / delete --------------------------------------------------------


@app.command("list")
def list_articles() -> None:
    """列出内容目录里的全部文章（任务书 §7.3）。

    这是排查"我到底在读哪个目录"最直接的命令：内容目录可以在四个地方配置，
    列表为空时应当先确认目录对不对，而不是怀疑文章丢了。
    """
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)
    locations = find_articles(content_root)
    next_id = next_article_id(content_root)

    if _json_output():
        from inloop import jsonapi

        items: list[dict] = []
        for location in locations:
            article = _try_parse(location)
            if article is None:
                items.append(
                    jsonapi.unparsable_to_dict(
                        location, base=content_root, reason="正文无法解析，请运行 check 查看原因"
                    )
                )
            else:
                items.append(jsonapi.article_to_dict(article, location, base=content_root))
        jsonapi.emit(jsonapi.list_payload(items, content_root=content_root, next_id=next_id))
        return

    console.print("[bold]内容目录[/bold]")
    console.print(f"  {content_root}")
    console.print("[bold]文章[/bold]")
    if not locations:
        hint = ""
        # 结构性误配提示：把年份子目录当成内容目录是最常见且最难自查的一种
        from inloop.jsonapi import misplaced_content_root_hint

        misplaced = misplaced_content_root_hint(content_root)
        if misplaced:
            hint = f"\n注意：{misplaced}"
        console.print("  （暂无文章）")
        console.print(
            "  新建：`inloop new --title \"标题\" --slug your-slug --template paper-note`"
        )
        if hint:
            console.print(f"[yellow]{escape(hint)}[/yellow]")
        return

    console.print(f"  共 {len(locations)} 篇，下一个编号 {next_id:03d}")
    console.print()
    for location in locations:
        article = _try_parse(location)
        if article is None:
            console.print(f"  [red]{location.dir_name}  无法解析，请运行 check 查看原因[/red]")
            continue
        number = f"{article.id:03d}" if location.number is not None else "---"
        console.print(
            f"  {number}  {escape(article.title)}  "
            f"[dim]{article.category.label} / {article.status} / {article.date.isoformat()}[/dim]"
        )


def _try_parse(location: ArticleLocation) -> Article | None:
    """尝试解析文章；失败返回 None，由调用方决定怎么提示。

    ``list`` 的职责是"列出有什么"，不能因为其中一篇写坏了就整个命令失败——
    那会让人连"有哪些文章"都看不到。解析失败的条目单独标出。
    """
    try:
        return Article.from_text(
            location.index.read_text(encoding="utf-8"), source=location.index
        )
    except (ArticleError, OSError):
        return None


@app.command()
def delete(
    target: str = typer.Argument(..., help="文章目录、index.md 路径或 slug"),
    yes: bool = typer.Option(
        False, "--yes", help="跳过确认，直接删除（供脚本与插件使用）"
    ),
) -> None:
    """删除一篇文章（任务书 §7.4）。

    **破坏性操作。** 内容目录通常不在 Git 里（可能由坚果云之类的同步盘管理），
    删掉的文章没有提交历史可回滚，因此默认会先列出将删除的文件并等待确认。

    ``--json`` 时**必须显式传 ``--yes``**：JSON 模式通常由程序调用，
    让程序去回答交互提问没有意义，而静默删除又太危险。
    """
    from inloop import jsonapi

    config = _config_or_fail()
    content_root = _content_root_or_fail(config)

    try:
        location = resolve_article(content_root, target)
    except ArticleNotFoundError as exc:
        _fail(str(exc), code="article_not_found")
        return

    article = _try_parse(location)
    files = sorted(p for p in location.directory.rglob("*") if p.is_file())
    image_count = sum(
        1 for p in files if p.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    )

    if _json_output():
        # JSON 模式下不接受交互确认：要么 --yes 明确删，要么返回预览并退出
        if not yes:
            jsonapi.emit(
                jsonapi.deletion_preview_payload(
                    location,
                    base=content_root,
                    image_count=image_count,
                    file_count=len(files),
                )
            )
            err_console.print(
                "[bold yellow]未传 --yes，未执行删除。[/bold yellow]"
                "如需删除请加 `--yes`。"
            )
            raise typer.Exit(code=EXIT_VALIDATION_FAILED)
        _do_delete(content_root, location, config, base=content_root)
        return

    # 先展示将要删除什么，再确认：只看目录名不足以判断删的是不是想要的那篇
    console.print("[bold]将要删除[/bold]")
    console.print(f"  目录：{_display_path(location.directory, config, content_root)}")
    if article is not None:
        console.print(f"  标题：{escape(article.title)}")
        console.print(f"  状态：{article.status}  编号：{article.id:03d}")

    console.print(f"  文件：{len(files)} 个（其中图片 {image_count} 张）")
    for path in files:
        console.print(f"    {path.relative_to(location.directory).as_posix()}")

    if article is not None and str(article.status) == Status.PUBLISHED.value:
        console.print(
            "[bold yellow]注意：这篇文章的状态是 published（已发布），"
            "删除后已发布的线上文章不会受影响，但本地不再有源文件。[/bold yellow]"
        )

    if not yes:
        console.print()
        if not _confirm("确认删除？此操作不可撤销"):
            console.print("已取消，未删除任何文件。")
            return

    try:
        result = delete_article(content_root, location)
    except ArticleDeletionError as exc:
        _fail(str(exc))
        return

    console.print(
        f"[bold green]✓[/bold green] 已删除 "
        f"{_display_path(result.location.directory, config, content_root)}"
        f"（{len(result.files)} 个文件，{_human_size(result.total_bytes)}）"
    )
    console.print("  提示：索引可能已过期，运行 `inloop index` 更新。")


def _do_delete(
    content_root: Path, location: ArticleLocation, config: Config, *, base: Path
) -> None:
    """执行删除并输出结果（JSON 与人类可读两种形式）。

    抽出来是为了让 JSON 路径与人读路径共用同一段删除逻辑——
    两处各写一遍必然漂移，而这是破坏性操作，不能有第二份实现。
    """
    from inloop import jsonapi

    try:
        result = delete_article(content_root, location)
    except ArticleDeletionError as exc:
        _fail(str(exc), code="delete_failed")
        return

    if _json_output():
        jsonapi.emit(jsonapi.delete_payload(result, base=base, removed=True))
        return

    console.print(
        f"[bold green]✓[/bold green] 已删除 "
        f"{_display_path(result.location.directory, config, content_root)}"
        f"（{len(result.files)} 个文件，{_human_size(result.total_bytes)}）"
    )
    console.print("  提示：索引可能已过期，运行 `inloop index` 更新。")


# --- 共用辅助 -------------------------------------------------------------


#: 预览页在产物目录中的文件名，供预览服务指定初始路径
ARTICLE_PREVIEW_NAME = "article.preview.html"


def _load_article_or_fail(
    config: Config, content_root: Path, target: str
) -> tuple[ArticleLocation, Article]:
    """定位并解析文章，失败时以统一格式退出。"""
    try:
        location = resolve_article(content_root, target)
    except ArticleNotFoundError as exc:
        _fail(str(exc), code="article_not_found", hint="用 `inloop list` 查看可用文章。")
        raise AssertionError("unreachable") from exc  # pragma: no cover

    try:
        article = Article.from_text(
            location.index.read_text(encoding="utf-8"), source=location.index
        )
    except ArticleError as exc:
        err_console.print(f"[bold red]✗[/bold red] {escape(str(exc))}")
        raise typer.Exit(code=EXIT_VALIDATION_FAILED) from exc
    return location, article


def _print_warnings(warnings: Sequence[str]) -> None:
    """统一展示构建过程中的非致命问题。"""
    if not warnings:
        return
    console.print(f"[bold yellow]提示（{len(warnings)}）[/bold yellow]")
    for warning in warnings:
        console.print(f"  [yellow]{escape(warning)}[/yellow]")


def _human_size(size: int) -> str:
    """字节数转人读形式。"""
    value = float(size)
    for unit in ("B", "KB", "MB"):
        if value < 1024 or unit == "MB":
            return f"{int(value)}{unit}" if unit == "B" else f"{value:.1f}{unit}"
        value /= 1024
    return f"{value:.1f}MB"


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
    config = _config_or_fail()
    content_root = _content_root_or_fail(config)

    try:
        location = resolve_article(content_root, target)
    except ArticleNotFoundError as exc:
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
