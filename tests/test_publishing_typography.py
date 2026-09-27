"""发布排版覆盖不得改写内容源，且必须真正进入构建产物。"""

import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from typer.testing import CliRunner

from inloop.build import build_article
from inloop.cli import app
from inloop.config import load_config
from inloop.models.article import Article
from inloop.typography import TypographyError, read_typography, save_typography


def test_中英文字体独立选择并进入产物(mini_repo: Path, mini_article) -> None:
    index, text = mini_article
    save_typography(mini_repo, mini_repo, 7, {"font_en": "Times New Roman"}, global_scope=True)
    save_typography(mini_repo, mini_repo, 7, {"font_zh": "楷体"})
    result = read_typography(mini_repo, mini_repo, 7)
    assert result["effective"] == {"font_en": "Times New Roman", "font_zh": "楷体"}
    outcome = build_article(
        Article.from_text(text, source=index),
        config=load_config(mini_repo), content_root=mini_repo,
    )
    soup = BeautifulSoup(
        (outcome.output_dir / "article.html").read_text(encoding="utf-8"), "html.parser",
    )
    for tag in (soup.body.div, soup.h1, soup.strong):
        family = tag["style"].split("font-family:")[1].split(";")[0]
        assert family.index("Times New Roman") < family.index("KaiTi")
        assert "STKaiti" in family
    assert "Times New Roman" not in soup.pre["style"]
    assert index.read_text(encoding="utf-8") == text


@pytest.mark.parametrize("font", ['x";color:red', "x,url(test)", "<script>", " ", "x" * 81])
def test_自定义字体只接受字体名称(mini_repo: Path, font: str) -> None:
    with pytest.raises(TypographyError):
        save_typography(mini_repo, mini_repo, 7, {"font_zh": font})


def test_自定义字体可保存且兼容原设置(mini_repo: Path) -> None:
    values = {"font_family": "serif", "font_zh": "华文行楷", "font_en": "Georgia"}
    save_typography(mini_repo, mini_repo, 7, values)
    assert read_typography(mini_repo, mini_repo, 7)["effective"] == values


def test_覆盖继承与恢复(mini_repo: Path) -> None:
    save_typography(mini_repo, mini_repo, 7, {"font_size": 18}, global_scope=True)
    save_typography(mini_repo, mini_repo, 7, {"line_height": 2, "font_size": 17})
    assert read_typography(mini_repo, mini_repo, 7)["effective"] == {
        "font_size": 17, "line_height": 2,
    }
    assert read_typography(mini_repo, mini_repo, 8)["effective"] == {"font_size": 18}
    assert read_typography(mini_repo, mini_repo / "other", 7)["article"] == {}
    save_typography(mini_repo, mini_repo, 7, {})
    assert read_typography(mini_repo, mini_repo, 7)["effective"] == {"font_size": 18}


@pytest.mark.parametrize("values", [
    {"font_size": 0}, {"font_size": True}, {"line_height": float("nan")},
    {"font_family": "arbitrary"}, {"extra": 1}, {"heading_size": "18"}, [],
])
def test_非法设置不落盘(mini_repo: Path, values: object) -> None:
    with pytest.raises(TypographyError):
        save_typography(mini_repo, mini_repo, 7, values)
    assert not (mini_repo / "config" / "publishing-typography.json").exists()


def test_产物覆盖主题且不改变代码与源文(mini_repo: Path, mini_article) -> None:
    index, text = mini_article
    article = Article.from_text(text, source=index)
    baseline = build_article(article, config=load_config(mini_repo), content_root=mini_repo)
    before = BeautifulSoup(
        (baseline.output_dir / "article.html").read_text(encoding="utf-8"), "html.parser",
    )
    values = {"font_family": "serif", "font_size": 18, "heading_size": 26,
              "line_height": 2, "paragraph_spacing": 25}
    save_typography(mini_repo, mini_repo, 7, values)
    outcome = build_article(article, config=load_config(mini_repo), content_root=mini_repo)
    html = (outcome.output_dir / "article.html").read_text(encoding="utf-8")
    soup = BeautifulSoup(html, "html.parser")
    assert "Songti SC" in soup.body.div["style"]
    assert set(soup.body.div.attrs) == {"style"}
    strong = soup.find("strong")
    assert "font-size:18px" in strong["style"]
    assert "serif" in strong["style"]
    assert "font-size:26px" in soup.h1["style"]
    assert "line-height:2" in strong["style"]
    assert "margin:0 0 25px" in strong.find_parent("p")["style"]
    assert str(soup.pre) == str(before.pre)
    caption = soup.img.parent.find_next_sibling("p")
    old_caption = before.img.parent.find_next_sibling("p")
    size_pattern = r"font-size:([^;]+)"
    import re

    assert re.search(size_pattern, caption["style"])[1] == re.search(
        size_pattern, old_caption["style"],
    )[1]
    assert index.read_text(encoding="utf-8") == text
    assert outcome.metadata["render_options"]["body_font_size"] == "18px"
    assert outcome.metadata["render_options"]["publishing_typography"] == values
    from inloop.publishers.wechat_api import WechatClient, WechatCredentials
    from inloop.publishers.wechat_publish import publish_article

    captured = []

    def transport(url, method, body, headers):
        if "/token?" in url:
            return json.dumps({"access_token": "test-token", "expires_in": 7200})
        if "/media/uploadimg?" in url:
            return json.dumps({"url": "https://mmbiz.qpic.cn/test-image"})
        if "/material/add_material?" in url:
            return json.dumps({"media_id": "test-cover"})
        if "/draft/add?" in url:
            captured.append(json.loads(body.decode("utf-8"))["articles"][0]["content"])
            return json.dumps({"media_id": "test-draft"})
        raise AssertionError(url)

    publish_article(
        repo_root=mini_repo, metadata=outcome.metadata, output_dir=outcome.output_dir,
        html_path=outcome.output_dir / "article.html",
        client=WechatClient(credentials=WechatCredentials("test-id", "test-secret"),
                            transport=transport),
    )
    sent = BeautifulSoup(captured[0], "html.parser")
    assert sent.strong["style"] == strong["style"]
    assert str(sent.pre) == str(soup.pre)
    assert "https://mmbiz.qpic.cn/test-image" in captured[0]


def test_CLI保存读取及拒绝错误配置(mini_repo: Path, mini_article, monkeypatch) -> None:
    monkeypatch.setenv("INLOOP_ROOT", str(mini_repo))
    runner = CliRunner()
    args = ["--json", "--content", str(mini_repo), "typography", "007-test-article"]
    result = runner.invoke(app, args + ["--settings", '{"font_size":19}'])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["effective"]["font_size"] == 19
    result = runner.invoke(app, args + ["--settings", '{"font_size":-1}'])
    assert result.exit_code == 1
    assert json.loads(runner.invoke(app, args).stdout)["effective"]["font_size"] == 19


def test_损坏配置明确报错且保留原文件(mini_repo: Path) -> None:
    path = mini_repo / "config" / "publishing-typography.json"
    path.write_text("{broken", encoding="utf-8")
    with pytest.raises(TypographyError, match="publishing-typography.json"):
        save_typography(mini_repo, mini_repo, 7, {})
    assert path.read_text(encoding="utf-8") == "{broken"
