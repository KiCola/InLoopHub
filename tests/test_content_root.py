"""内容与工具解耦的测试（任务书 §3）。

覆盖三件事：

1. ``content_root`` 的四级解析顺序
2. 内容目录位于**工具仓库之外**时，"新建 / 列表 / 检查 / 索引 / 构建"整条链路可用
3. 删除操作的安全边界

第 2 条是这套改动的核心断言。它同时验证了一件容易忽略的事：
**产物里不得出现本机绝对路径**——内容在仓库外时，
"算不出相对路径就回退成绝对路径"会从异常分支变成正常分支，
把 ``C:\\Users\\...`` 写进 metadata.json。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from inloop.articles import (
    ArticleDeletionError,
    NewArticleRequest,
    create_article,
    delete_article,
    find_articles,
    next_article_id,
    resolve_article,
)
from inloop.cli import app
from inloop.config import Config, ConfigError, load_config
from inloop.models.article import Category

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT)

runner = CliRunner()


def make_article(content_root: Path, slug: str = "ext-test", number: int = 1) -> Path:
    """在指定内容目录里造一篇文章（含封面与一张配图）。"""
    directory = content_root / "2026" / f"{number:03d}-{slug}"
    (directory / "assets").mkdir(parents=True)
    Image.new("RGB", (600, 300), (0, 47, 167)).save(directory / "assets" / "pic.png")
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(directory / "cover.png")
    (directory / "index.md").write_text(
        "---\n"
        f"id: {number}\n"
        f'title: "外部内容文章 {slug}"\n'
        f'slug: "{slug}"\n'
        "date: 2026-09-25\n"
        'author: "测试作者"\n'
        'category: "paper"\n'
        'status: "draft"\n'
        "tags:\n"
        "  - 测试\n"
        'summary: "验证内容与工具解耦。"\n'
        'cover: "cover.png"\n'
        "platforms:\n"
        "  wechat: true\n"
        "---\n"
        "\n"
        f"# 外部内容文章 {slug}\n"
        "\n"
        "## 01 · 第一节\n"
        "\n"
        "正文段落。\n"
        "\n"
        '![示意图](assets/pic.png "图 1：示意")\n',
        encoding="utf-8",
        newline="\n",
    )
    return directory


@pytest.fixture()
def external_content(tmp_path: Path) -> Path:
    """一个**与工具仓库无关**的内容目录。

    放在 tmp_path 下（不依赖作者的真实 vault），结构与真实内容目录一致：
    ``<content_root>/2026/<文章>/``。
    """
    root = tmp_path / "external-content"
    root.mkdir()
    return root


# --- content_root 解析 ----------------------------------------------------


def test_兜底到仓库内的_articles() -> None:
    """四级都没配置时回退到 <repo>/articles，保证开箱可用。"""
    resolved = CONFIG.resolve_content_root()
    assert resolved == CONFIG.root / "articles"


def test_命令行参数优先级最高(external_content: Path) -> None:
    assert CONFIG.resolve_content_root(external_content) == external_content.resolve()


def test_环境变量次之(external_content: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INLOOP_CONTENT", str(external_content))
    assert CONFIG.resolve_content_root() == external_content.resolve()
    # 命令行参数仍然压过环境变量
    other = external_content.parent / "external-content"
    assert CONFIG.resolve_content_root(other) == other.resolve()


def test_内容目录不存在时报错并指明来源(tmp_path: Path) -> None:
    """不允许静默回退：读错目录比报错危险得多。"""
    missing = tmp_path / "not-exist"
    with pytest.raises(ConfigError) as excinfo:
        CONFIG.resolve_content_root(missing)
    message = str(excinfo.value)
    assert str(missing) in message
    assert "--content" in message


def test_配置里的空字符串视为未配置() -> None:
    """`root: ""` 是最自然的"留空"写法，必须走兜底而不是报错。"""
    empty = Config(
        root=CONFIG.root,
        site=CONFIG.site,
        brand=CONFIG.brand,
        wechat=CONFIG.wechat,
        content={"root": ""},
    )
    assert empty.resolve_content_root() == CONFIG.root / "articles"


def test_构建产物目录可配置(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    target = tmp_path / "dist-here"
    monkeypatch.setenv("INLOOP_DIST", str(target))
    assert CONFIG.resolve_dist_root() == target.resolve()


# --- 仓库外的内容目录：整条链路 -------------------------------------------


def test_在仓库外目录新建文章(external_content: Path) -> None:
    result = create_article(
        external_content,
        REPO_ROOT,
        NewArticleRequest(
            title="仓库外新建",
            slug="outside",
            category=Category.PAPER,
            year=2026,
            template="paper-note",
            author="测试作者",
            tags=("测试",),
            summary="摘要。",
        ),
    )
    # 文章写在内容目录里，模板从工具仓库读——两个根各司其职
    assert result.location.directory.is_relative_to(external_content)
    assert result.location.index.is_file()
    assert (result.location.directory / "cover.png").is_file()
    assert result.article.title == "仓库外新建"


def test_仓库外内容的编号独立计算(external_content: Path) -> None:
    """编号以内容目录为准，与工具仓库里的 examples/ 互不干扰。"""
    make_article(external_content, slug="a", number=1)
    make_article(external_content, slug="b", number=7)
    assert next_article_id(external_content) == 8
    # 仓库内的示例文章不影响它
    assert len(find_articles(external_content)) == 2


def test_构建仓库外文章不写绝对路径(external_content: Path) -> None:
    """核心断言：产物里不得出现本机绝对路径。

    内容在仓库外时，`relative_to(repo_root)` 必然失败。
    如果代码"失败就回退成绝对路径"，metadata.json 会写进
    `C:\\Users\\...`，既泄漏目录结构又让产物不可复现。
    """
    from inloop.build import ARTICLE_HTML, build_article
    from inloop.models.article import Article

    directory = make_article(external_content)
    index = directory / "index.md"
    article = Article.from_text(index.read_text(encoding="utf-8"), source=index)
    assert not article.errors, [i.render() for i in article.errors]

    outcome = build_article(
        article, config=CONFIG, content_root=external_content
    )
    raw = (outcome.output_dir / "metadata.json").read_text(encoding="utf-8")
    metadata = json.loads(raw)

    # source 相对内容目录，形如 2026/001-ext-test/index.md
    assert metadata["source"].startswith("2026/")
    assert not Path(metadata["source"]).is_absolute()

    # 整个 metadata 里不得出现盘符
    import re

    drives = re.findall(r"[A-Za-z]:[\\/]", raw)
    assert drives == [], f"产物里出现了绝对路径：{drives}"

    # 图片清单里的源路径同样相对内容目录
    for entry in metadata["images"]:
        assert not Path(entry["source"]).is_absolute(), entry["source"]
        assert not re.search(r"[A-Za-z]:[\\/]", entry["source"]), entry["source"]

    # 正文 HTML 里也不该有本地路径
    html = (outcome.output_dir / ARTICLE_HTML).read_text(encoding="utf-8")
    assert not re.search(r"[A-Za-z]:[\\/]", html)


# --- 删除的安全边界 -------------------------------------------------------


def test_删除文章会清掉整个目录(external_content: Path) -> None:
    directory = make_article(external_content)
    location = resolve_article(external_content, "001-ext-test")

    result = delete_article(external_content, location)

    assert not directory.exists()
    # 清单在删除前收集，因此仍能报出删了什么
    assert "index.md" in result.files
    assert "cover.png" in result.files
    assert result.image_count == 2  # cover.png + assets/pic.png
    assert result.total_bytes > 0


def test_拒绝删除内容目录本身(external_content: Path) -> None:
    """误传内容目录时不能让整个内容目录被删掉。"""
    make_article(external_content)
    location = resolve_article(external_content, "001-ext-test")
    rogue = location.__class__(
        directory=external_content,
        index=location.index,
        dir_name=external_content.name,
        number=None,
        slug=None,
    )
    with pytest.raises(ArticleDeletionError, match="不在内容目录内|拒绝删除"):
        delete_article(external_content, rogue)
    assert external_content.is_dir()


def test_拒绝删除内容目录之外的目标(external_content: Path, tmp_path: Path) -> None:
    """目标被解析到内容目录外面时必须拒绝，避免删除范围失控。"""
    outside = tmp_path / "outside-dir"
    outside.mkdir()
    make_article(external_content)
    real = resolve_article(external_content, "001-ext-test")
    rogue = real.__class__(
        directory=outside,
        index=outside / "index.md",
        dir_name="outside-dir",
        number=None,
        slug=None,
    )
    with pytest.raises(ArticleDeletionError):
        delete_article(external_content, rogue)
    assert outside.is_dir()


def test_删除不存在的文章给出可定位错误(external_content: Path) -> None:
    from inloop.articles import ArticleNotFoundError

    with pytest.raises(ArticleNotFoundError) as excinfo:
        resolve_article(external_content, "does-not-exist")
    assert "does-not-exist" in str(excinfo.value)


# --- CLI 层 ---------------------------------------------------------------


def test_命令行_content_参数生效(external_content: Path) -> None:
    make_article(external_content)
    result = runner.invoke(app, ["--content", str(external_content), "list"])
    assert result.exit_code == 0, result.output
    assert "外部内容文章 ext-test" in result.output
    assert str(external_content) in result.output


def test_info_打印内容目录与来源(external_content: Path) -> None:
    """"读错目录"是最容易犯的错，因此必须显式报告来源。"""
    result = runner.invoke(app, ["--content", str(external_content), "info"])
    assert result.exit_code == 0, result.output
    assert "内容目录" in result.output
    assert "命令行参数 --content" in result.output


def test_命令行_content_指向不存在的目录即失败(tmp_path: Path) -> None:
    missing = tmp_path / "nope"
    result = runner.invoke(app, ["--content", str(missing), "list"])
    assert result.exit_code != 0
    # Rich 会按终端宽度对长路径折行，因此比较前去掉换行符
    compact = result.output.replace("\n", "")
    assert str(missing).replace("\n", "") in compact
    assert "内容目录不存在" in compact


def test_check_all_对空目录不算通过(external_content: Path) -> None:
    """空目录不能报"检查通过"——那会给出虚假的安心感。"""
    result = runner.invoke(app, ["--content", str(external_content), "check", "--all"])
    assert result.exit_code != 0
    assert "没有文章" in result.output


def test_delete_非交互环境不加_yes_不删除(external_content: Path) -> None:
    directory = make_article(external_content)
    result = runner.invoke(app, ["--content", str(external_content), "delete", "001-ext-test"])
    # CliRunner 的输入不是 tty，无法确认 -> 不删除
    assert directory.exists()
    assert result.exit_code != 0 or "取消" in result.output or "无法" in result.output


def test_delete_加_yes_执行删除(external_content: Path) -> None:
    directory = make_article(external_content)
    result = runner.invoke(
        app, ["--content", str(external_content), "delete", "001-ext-test", "--yes"]
    )
    assert result.exit_code == 0, result.output
    assert not directory.exists()
