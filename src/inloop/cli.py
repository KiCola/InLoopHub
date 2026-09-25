"""命令行入口。

设计约定：

- 命令只做「解析参数 → 调用实现 → 打印结果 → 返回退出码」，业务逻辑不写在这里。
- 未实现的命令**不注册**，避免 ``--help`` 里出现点了没反应的入口（AGENTS.md §3 不谎报）。
  任务书 §7 要求的 ``new`` / ``check`` / ``build-wechat`` / ``preview-wechat`` / ``index``
  会在各自模块完成后逐条接入。
- 退出码：成功 0；校验失败等预期内的失败 1；用法错误由 Typer 负责（2）。
"""

from __future__ import annotations

import typer
from rich.console import Console
from rich.markup import escape

from inloop import __version__
from inloop.config import ConfigError, load_config, repo_root

app = typer.Typer(
    name="inloop",
    help="InLoop 手记：把 Markdown 内容仓库构建为微信公众号文章。",
    no_args_is_help=True,
    add_completion=False,
)

console = Console()


def _fail(message: str) -> None:
    """以统一格式输出错误并退出。错误信息必须包含修正建议。"""
    console.print(f"[bold red]✗[/bold red] {escape(message)}")
    raise typer.Exit(code=1)


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

    site_name = config.site_value("name")
    author = config.site_value("author")
    primary = config.brand_value("primary")
    font_size = config.wechat_value("font_size")
    line_height = config.wechat_value("line_height")
    heading_style = config.wechat_value("heading_style")

    console.print("[bold]站点[/bold]")
    console.print(f"  名称：{site_name}")
    console.print(f"  作者：{author}")
    console.print("[bold]品牌[/bold]")
    console.print(f"  主色：{primary}")
    console.print("[bold]微信渲染[/bold]")
    console.print(f"  正文字号：{font_size}px")
    console.print(f"  行高：{line_height}")
    console.print(f"  标题样式：{heading_style}")


@app.command()
def root() -> None:
    """只输出仓库根路径，便于脚本与其他工具复用。"""
    try:
        console.print(str(repo_root()))
    except ConfigError as exc:
        _fail(str(exc))


if __name__ == "__main__":  # pragma: no cover - 手动调试用
    app()
