"""Front Matter 解析与文章模型的测试（任务书 §22）。

覆盖重点：front matter 解析、空字段、Unicode、中文标题、以及全部失败路径
是否报出**稳定的规则码**——规则码是对外契约，行为变化必须被测试发现。
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from inloop.models.article import Article, ArticleError, Category, Status
from inloop.models.serializer import dump_front_matter, render_article_text
from inloop.parser.frontmatter import FrontMatterError, parse_front_matter
from inloop.rules import RULES_BY_CODE
from tests.conftest import MINIMAL_BODY, MINIMAL_FRONT, make_article_text

SOURCE = Path("content/2026/007-test-article/index.md")


def codes(text: str, source: Path | None = SOURCE) -> list[str]:
    """解析文本并返回全部规则码。"""
    try:
        return [issue.code for issue in Article.from_text(text, source=source).issues]
    except ArticleError:
        return ["<结构错误>"]


# --- 解析 -----------------------------------------------------------------


def test_解析合法文章(article_text: str) -> None:
    article = Article.from_text(article_text, source=SOURCE)
    assert article.id == 7
    assert article.title == "测试文章"
    assert article.slug == "test-article"
    assert article.date == date(2026, 9, 25)
    assert article.category is Category.RESEARCH
    assert article.status is Status.DRAFT
    assert article.tags == ("标签一", "标签二")
    assert article.platforms["wechat"] is True
    assert article.directory_name == "007-test-article"
    assert not article.issues, [i.render() for i in article.issues]


def test_正文原样保留且不含_front_matter(article_text: str) -> None:
    article = Article.from_text(article_text)
    assert article.body.startswith("\n# 测试标题")
    assert "slug:" not in article.body


def test_未知字段被保留(article_text: str) -> None:
    text = article_text.replace("cover: \"cover.png\"", "cover: \"cover.png\"\ncustom_field: 值")
    article = Article.from_text(text)
    assert article.extra.get("custom_field") == "值"


def test_允许_BOM_与_CRLF(article_text: str) -> None:
    with_bom = "\ufeff" + article_text
    assert Article.from_text(with_bom).id == 7
    crlf = article_text.replace("\n", "\r\n")
    assert Article.from_text(crlf).title == "测试文章"


@pytest.mark.parametrize(
    ("name", "text"),
    [
        ("缺少整体 front matter", "# 只有正文\n"),
        ("未闭合定界符", "---\nid: 1\n# 没有结束符\n"),
        ("空块", "---\n---\n# 标题\n"),
        ("Tab 缩进", "---\nid: 1\n\ttitle: x\n---\n# 标题\n"),
        ("顶层是列表", "---\n- a\n- b\n---\n# 标题\n"),
    ],
)
def test_结构性错误抛异常(name: str, text: str) -> None:
    with pytest.raises(ArticleError):
        Article.from_text(text, source=SOURCE)


def test_空文件给出可读错误() -> None:
    with pytest.raises(FrontMatterError, match="内容为空"):
        parse_front_matter("   \n\n")


# --- 字段校验：每个规则码 -------------------------------------------------

FIELD_CASES: list[tuple[str, str, str, str]] = [
    # (说明, 原文片段, 替换为, 期望规则码)
    ("缺少全部可选字段", MINIMAL_FRONT, "---\nid: 7\ntitle: \"t\"\n---\n", "FM001"),
    ("id 非整数", "id: 7", "id: abc", "FM008"),
    ("title 为空", 'title: "测试文章"', 'title: ""', "FM010"),
    ("title 是数字", 'title: "测试文章"', "title: 123", "FM009"),
    ("slug 非法", 'slug: "test-article"', 'slug: "Bad_Slug"', "FM002"),
    ("date 斜杠", "date: 2026-09-25", "date: 2026/09/25", "FM011"),
    ("date 不存在", "date: 2026-09-25", "date: 2026-02-30", "FM011"),
    ("date 不存在(加引号)", "date: 2026-09-25", 'date: "2026-02-30"', "FM011"),
    ("status 非法", 'status: "draft"', 'status: "done"', "FM013"),
    ("category 非法", 'category: "research"', 'category: "news"', "FM012"),
    ("tags 标量", "tags:\n  - 标签一\n  - 标签二\n", "tags: 标签一\n", "FM014"),
    (
        "platforms 非映射",
        "platforms:\n  wechat: true\n  blog: false\n",
        "platforms: yes\n",
        "FM015",
    ),
    ("wechat 未开启", "  wechat: true\n", "  wechat: false\n", "FM016"),
]


@pytest.mark.parametrize(("name", "old", "new", "expected"), FIELD_CASES)
def test_字段问题报出对应规则码(name: str, old: str, new: str, expected: str) -> None:
    text = (MINIMAL_FRONT + "\n" + MINIMAL_BODY).replace(old, new)
    assert expected in codes(text)


def test_每个报出的规则码都在规则表中() -> None:
    """报了表里没有的码，用户无从查起——这属于程序缺陷。"""
    text = make_article_text(
        front="---\nid: x\ntitle: 1\n---\n",
        body="没有标题",
    )
    for code in codes(text):
        assert code in RULES_BY_CODE, f"未登记的规则码：{code}"


# --- 警告级 ---------------------------------------------------------------


def test_tags_为空给警告() -> None:
    # 注意替换范围：必须把 `tags:` 一行一起替换成 `tags: []`。
    # 只替换列表项会得到 `tags:\n[]`，那是非法 YAML，测的就不是「空列表」了。
    text = make_article_text(
        front=MINIMAL_FRONT.replace("tags:\n  - 标签一\n  - 标签二\n", "tags: []\n")
    )
    assert "FM003" in codes(text)


def test_摘要过长给警告() -> None:
    text = make_article_text(front=MINIMAL_FRONT.replace('"一句话摘要。"', '"' + "长" * 130 + '"'))
    assert "FM005" in codes(text)


def test_未来日期给警告() -> None:
    text = make_article_text(front=MINIMAL_FRONT.replace("2026-09-25", "2099-01-01"))
    assert "FM006" in codes(text)


def test_正文缺一级标题给警告() -> None:
    text = make_article_text(body="只有正文，没有标题\n")
    assert "FM007" in codes(text)


def test_目录名序号与id不一致给警告() -> None:
    text = make_article_text()
    assert "FM018" in codes(text, source=Path("content/2026/099-test-article/index.md"))


def test_id报错时不再产生误导性的目录名警告() -> None:
    """id 解析失败时若继续比对目录名，会拿占位值 0 去比，产生无意义的警告。"""
    text = make_article_text(front=MINIMAL_FRONT.replace("id: 7", "id: abc"))
    result = codes(text)
    assert "FM008" in result
    assert "FM018" not in result


# --- 序列化 ---------------------------------------------------------------


def test_序列化往返一致(article_text: str) -> None:
    original = Article.from_text(article_text, source=SOURCE)
    reparsed = Article.from_text(original.to_markdown(), source=SOURCE)

    for field in ("id", "title", "slug", "date", "author", "category", "status",
                  "tags", "summary", "cover", "platforms"):
        assert getattr(original, field) == getattr(reparsed, field), field
    assert original.body.strip() == reparsed.body.strip()
    assert not reparsed.issues


def test_序列化不转义中文(article_text: str) -> None:
    text = Article.from_text(article_text).to_markdown()
    assert "测试文章" in text
    assert "\\u" not in text


def test_序列化保留未定义字段(article_text: str) -> None:
    """解析再写回时，模型未识别的字段不能丢。

    手写字典调 dump_front_matter 测不出这个问题——必须走模型的往返，
    否则「extra 在序列化时被丢掉」这类缺陷不会被发现。
    """
    text = article_text.replace('cover: "cover.png"', 'cover: "cover.png"\nextra_thing: "保留我"')
    article = Article.from_text(text)
    assert article.extra["extra_thing"] == "保留我"

    dumped = article.to_markdown()
    assert "保留我" in dumped
    assert Article.from_text(dumped).extra["extra_thing"] == "保留我"


def test_序列化输出以换行结尾且为_LF(article_text: str) -> None:
    text = render_article_text(Article.from_text(article_text))
    assert text.endswith("\n")
    assert "\r" not in text


def test_枚举可被_YAML_序列化() -> None:
    """StrEnum 无法被 yaml.safe_dump 直接序列化，必须由 dumper 显式处理。"""
    article = Article.from_text(make_article_text())
    dumped = dump_front_matter(
        {"category": str(article.category), "status": str(article.status)}
    )
    assert "category: research" in dumped
    assert "status: draft" in dumped


def test_空值写为空字符串而不是_null() -> None:
    dumped = dump_front_matter({"id": 1, "summary": None})
    assert "summary: ''" in dumped or 'summary: ""' in dumped
    assert "null" not in dumped
