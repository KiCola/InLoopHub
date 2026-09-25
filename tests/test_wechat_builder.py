"""微信构建器的端到端测试（任务书 §22、§27）。

本文件的关键部分是对**仓库里真实的 4 篇文章**做完整构建，而不是只测人造样例。
任务书 §28 的要求很明确：只用简单样例测试，会出现"测试页面很好看、
真正技术文章一塌糊涂"的结果。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from inloop.build import (
    ARTICLE_HTML,
    METADATA_JSON,
    PREVIEW_HTML,
    BuildError,
    build_article,
)
from inloop.config import load_config
from inloop.models.article import Article
from inloop.renderer.wechat import theme_name
from inloop.rendering import read_theme_from_html

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT)

#: 仓库内真实文章目录，按任务书 §28 的计划
REAL_ARTICLES = sorted((REPO_ROOT / "articles" / "2026").glob("[0-9]*-*/index.md"))


def load_article(index: Path) -> Article:
    return Article.from_text(index.read_text(encoding="utf-8"), source=index)


def digest_tree(directory: Path) -> dict[str, str]:
    """对目录内所有文件取内容哈希。"""
    result: dict[str, str] = {}
    for path in sorted(directory.rglob("*")):
        if path.is_file():
            relative = path.relative_to(directory).as_posix()
            result[relative] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def test_仓库中存在四篇真实文章() -> None:
    """示例文章是验收的一部分，缺失说明仓库状态不对。"""
    assert len(REAL_ARTICLES) >= 4, [p.as_posix() for p in REAL_ARTICLES]


@pytest.mark.parametrize("index", REAL_ARTICLES, ids=lambda p: p.parent.name)
def test_真实文章无_ERROR(index: Path) -> None:
    article = load_article(index)
    assert not article.errors, [i.render() for i in article.errors]


@pytest.mark.parametrize("index", REAL_ARTICLES, ids=lambda p: p.parent.name)
def test_真实文章可以构建(index: Path) -> None:
    article = load_article(index)
    outcome = build_article(article, config=CONFIG)
    output = outcome.output_dir
    assert output.is_dir()

    # 任务书 §8 要求的五项产物
    assert (output / ARTICLE_HTML).is_file()
    assert (output / PREVIEW_HTML).is_file()
    assert (output / METADATA_JSON).is_file()
    assert (output / article.cover).is_file()


@pytest.mark.parametrize("index", REAL_ARTICLES, ids=lambda p: p.parent.name)
def test_真实文章产物的正文满足微信兼容要求(index: Path) -> None:
    article = load_article(index)
    outcome = build_article(article, config=CONFIG)
    html = (outcome.output_dir / ARTICLE_HTML).read_text(encoding="utf-8")

    # 任务书 §9.2、§27：不依赖外部 CSS、不依赖 JS
    assert "<script" not in html
    assert "<style" not in html
    assert "<link" not in html
    assert "<iframe" not in html
    # 产物要求零 class / 零 id
    assert "class=" not in html
    assert "id=" not in html
    # 正文容器应带内联样式
    assert 'style="' in html


@pytest.mark.parametrize("index", REAL_ARTICLES, ids=lambda p: p.parent.name)
def test_真实文章产物中的图片都存在(index: Path) -> None:
    article = load_article(index)
    outcome = build_article(article, config=CONFIG)
    metadata = json.loads((outcome.output_dir / METADATA_JSON).read_text(encoding="utf-8"))

    assert metadata["images"], "文章应当至少包含一张图片"
    for relative in metadata["images"]:
        target = outcome.output_dir / relative
        assert target.is_file(), relative
        assert target.stat().st_size > 0


@pytest.mark.parametrize("index", REAL_ARTICLES, ids=lambda p: p.parent.name)
def test_构建不改动源文件(index: Path) -> None:
    """内容源是唯一事实源，构建产物不得反向影响它。"""
    before = hashlib.sha256(index.read_bytes()).hexdigest()
    build_article(load_article(index), config=CONFIG)
    assert hashlib.sha256(index.read_bytes()).hexdigest() == before


def test_确定性_固定时间后两次构建逐字节一致(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """metadata.json 带生成时间，因此必须能固定它，否则无法验证可复现性。"""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1767225600")
    index = REAL_ARTICLES[0]
    article = load_article(index)

    first = build_article(article, config=CONFIG)
    first_digest = digest_tree(first.output_dir)

    second = build_article(article, config=CONFIG)
    second_digest = digest_tree(second.output_dir)

    assert first_digest == second_digest
    # 顺带确认没有中间态临时文件残留
    assert not list(second.output_dir.rglob("*.tmp"))


def test_元数据字段与键序稳定() -> None:
    article = load_article(REAL_ARTICLES[0])
    outcome = build_article(article, config=CONFIG)
    raw = (outcome.output_dir / METADATA_JSON).read_text(encoding="utf-8")
    metadata = json.loads(raw)

    assert list(metadata) == [
        "title",
        "summary",
        "author",
        "date",
        "cover",
        "source",
        "status",
        "platform",
        "slug",
        "category",
        "tags",
        "images",
        "byline",
        "byline_note",
        "render_options",
        "generated_at",
    ]
    assert metadata["platform"] == "wechat"
    # 中文不转义，便于人工查看
    assert "\\u" not in raw
    # source 用仓库相对路径
    assert metadata["source"].startswith("articles/")
    assert not Path(metadata["source"]).is_absolute()


def test_渲染选项被记录且与产物一致() -> None:
    """样式会不断调整，产物里必须能查到"当时用的是哪套选项"。

    记录值必须与产物里真正写入的值一致——不一致比不记录更糟，
    会让人以为观感是 A、实际是 B。
    """
    import re

    article = load_article(REAL_ARTICLES[0])
    outcome = build_article(article, config=CONFIG)
    metadata = json.loads((outcome.output_dir / METADATA_JSON).read_text(encoding="utf-8"))
    options = metadata["render_options"]

    assert options["theme"] == theme_name(CONFIG)
    assert options["body_font_size"]
    assert options["body_line_height"]
    assert options["paragraph_spacing"]

    html = (outcome.output_dir / ARTICLE_HTML).read_text(encoding="utf-8")
    # 必须取**正文**里的段落，排除两类：
    # - 卡片内的段落：卡片有自己的内距，而 render_options 记录的是正文段距
    # - 落款区内的段落：那是刊物式头部，字号与正文不同
    from bs4 import BeautifulSoup

    container = BeautifulSoup(html, "html.parser").find("div")
    assert container is not None
    body_paragraph = next(
        (
            p
            for p in container.find_all("p")
            if p.find_parent("blockquote") is None and p.find_parent("section") is None
        ),
        None,
    )
    assert body_paragraph is not None, "文章应至少有一个正文段落"

    style = body_paragraph.get("style") or ""
    assert f"font-size:{options['body_font_size']}" in style
    assert f"line-height:{options['body_line_height']}" in style

    # 段落间距可能写作 `margin` 简写，也可能写作 `margin-bottom`；
    # 按 CSS 的展开规则取实际生效的下边距，避免把断言绑死在写法上。
    spacing = options["paragraph_spacing"]
    shorthand = re.search(r"margin:([^;]+)", style)
    if shorthand:
        parts = shorthand.group(1).split()
        bottom = parts[0] if len(parts) == 1 else (parts[0] if len(parts) == 2 else parts[2])
        assert bottom == spacing, f"简写中的下边距 {bottom} 与记录 {spacing} 不一致"
    else:
        assert f"margin-bottom:{spacing}" in style


def test_产物_HTML_记录主题名() -> None:
    """只拿到一个 HTML 文件时，也应能判断它是哪个主题渲染的。"""
    article = load_article(REAL_ARTICLES[0])
    outcome = build_article(article, config=CONFIG)

    for name in (ARTICLE_HTML, PREVIEW_HTML):
        html = (outcome.output_dir / name).read_text(encoding="utf-8")
        assert read_theme_from_html(html) == theme_name(CONFIG), name


def test_指定主题时记录的值随主题变化() -> None:
    """临时换主题构建，产物与记录都要跟着变。

    注意：两次构建写的是同一个产物目录，因此必须在**每次构建后立刻**读取
    它自己返回的 metadata，不能等两次都建完再去读文件——那样读到的是后一次的覆盖结果。
    """
    article = load_article(REAL_ARTICLES[0])

    default_options = build_article(article, config=CONFIG).metadata["render_options"]
    other_options = build_article(article, config=CONFIG, theme="generous").metadata[
        "render_options"
    ]

    assert default_options["theme"] == theme_name(CONFIG)
    assert other_options["theme"] == "generous"
    assert other_options["body_line_height"] != default_options["body_line_height"]


def test_有_ERROR_时拒绝构建且不产出文件(mini_repo: Path) -> None:
    index = mini_repo / "articles" / "2026" / "001-bad" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text("---\nid: 1\ntitle: \"\"\n---\n# 标题\n", encoding="utf-8")

    article = Article.from_text(index.read_text(encoding="utf-8"), source=index)
    assert article.errors, "该样例应当存在 ERROR"

    config = load_config(mini_repo)
    with pytest.raises(BuildError, match="ERROR"):
        build_article(article, config=config)
    assert not (mini_repo / "dist").exists()


def test_缺图片时拒绝构建(mini_repo: Path) -> None:
    """正文引用的图片不存在时，构建必须中止而不是产出一个缺图的产物。"""
    index = mini_repo / "articles" / "2026" / "007-test-article" / "index.md"
    index.parent.mkdir(parents=True)
    index.write_text(
        "---\n"
        "id: 7\n"
        'title: "标题"\n'
        'slug: "test-article"\n'
        "date: 2026-09-25\n"
        'author: "作者"\n'
        'category: "diary"\n'
        'status: "draft"\n'
        "tags:\n"
        "  - 标签\n"
        'summary: "摘要"\n'
        'cover: "cover.png"\n'
        "platforms:\n"
        "  wechat: true\n"
        "---\n"
        "# 标题\n\n"
        "![缺失的图](assets/nonexistent.png)\n",
        encoding="utf-8",
    )
    article = Article.from_text(index.read_text(encoding="utf-8"), source=index)
    assert not article.errors

    with pytest.raises(BuildError, match="IMG001|IMG003|封面"):
        build_article(article, config=load_config(mini_repo))


def test_预览页带手机宽度外壳() -> None:
    article = load_article(REAL_ARTICLES[0])
    outcome = build_article(article, config=CONFIG)
    preview = (outcome.output_dir / PREVIEW_HTML).read_text(encoding="utf-8")
    assert "max-width:430px" in preview
    assert "viewport" in preview
    assert 'charset="utf-8"' in preview
    # 预览外壳不得引入外部资源
    assert "<link" not in preview
    assert "<script" not in preview


def test_产物清单为相对路径() -> None:
    """绝对路径既泄漏本机目录结构，也让清单无法跨机器复用。"""
    article = load_article(REAL_ARTICLES[0])
    outcome = build_article(article, config=CONFIG)
    for relative in outcome.files:
        assert not relative.is_absolute(), relative
        assert (outcome.output_dir / relative).exists(), relative
