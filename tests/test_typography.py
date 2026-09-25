"""落款区、标题自动编号、重点段落的测试。

这三项都是"排版表达力"的功能，共同点是**写法与呈现的对应关系必须固定**：
作者写什么、渲染成什么，一旦漂移就会让人对排版失去预期。因此这里逐条固定。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from inloop.config import load_config
from inloop.normalize import normalize_html
from inloop.parser.markdown import render_markdown
from inloop.renderer.wechat import (
    apply_heading_numbers,
    load_stylesheet,
    prepend_byline,
    render_wechat_html,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT)
SHEET = load_stylesheet(CONFIG, "inloop")


def render(body: str, *, heading_numbers: bool = True, **kwargs: object) -> BeautifulSoup:
    """渲染一段正文。

    默认开启标题自动编号：本文件里绝大多数用例都在验证编号行为，
    需要验证"关闭时"的用例显式传 ``heading_numbers=False``。
    """
    html = normalize_html(render_markdown(body).html).html
    result = render_wechat_html(
        html, config=CONFIG, stylesheet=SHEET, heading_numbers=heading_numbers, **kwargs
    )
    return BeautifulSoup(result.html, "html.parser")


# --- 标题自动编号 ---------------------------------------------------------


def test_只给二级标题编号() -> None:
    soup = render("# 大标题\n\n## Problem\n\n### 细节\n\n## Method\n", heading_numbers=True)
    assert soup.find("h1").get_text() == "大标题"
    assert soup.find("h3").get_text() == "细节"
    assert [h.get_text() for h in soup.find_all("h2")] == ["01 · Problem", "02 · Method"]


def test_编号可关闭() -> None:
    soup = render("## Problem\n", heading_numbers=False)
    assert soup.find("h2").get_text() == "Problem"


def test_已有编号不会被叠加() -> None:
    """作者手写的编号必须被识别，否则会变成 `01 · 01 · Problem`。"""
    soup = render("## 01 · Problem\n\n## Method\n", heading_numbers=True)
    texts = [h.get_text() for h in soup.find_all("h2")]
    assert texts == ["01 · Problem", "02 · Method"]


@pytest.mark.parametrize(
    "written",
    ["01 · Problem", "1. Problem", "01、Problem", "01: Problem", "01 Problem"],
)
def test_各种手写编号写法都能被识别(written: str) -> None:
    soup = render(f"## {written}\n\n## Next\n", heading_numbers=True)
    texts = [h.get_text() for h in soup.find_all("h2")]
    assert texts[0] == written, "手写编号不应被改写"
    assert texts[1] == "02 · Next"


def test_编号位数与分隔符可配置() -> None:
    body = normalize_html(render_markdown("## Problem\n").html).html
    soup = BeautifulSoup(body, "html.parser")
    count = apply_heading_numbers(soup, enabled=True, separator=" - ", padding=3)
    assert count == 1
    assert soup.find("h2").get_text() == "001 - Problem"


def test_编号数量被返回() -> None:
    body = normalize_html(render_markdown("## A\n\n## B\n\n## C\n").html).html
    soup = BeautifulSoup(body, "html.parser")
    assert apply_heading_numbers(soup, enabled=True) == 3


def test_空标题不参与编号() -> None:
    body = "<h2> </h2><h2>有内容</h2>"
    soup = BeautifulSoup(body, "html.parser")
    apply_heading_numbers(soup, enabled=True)
    assert soup.find_all("h2")[1].get_text().endswith("有内容")


# --- 落款区 ---------------------------------------------------------------


def test_落款区渲染在正文最前() -> None:
    soup = render("# 标题\n\n正文。\n", byline="Minds in AI.", byline_note="InLoop 编辑部")
    first = soup.find("div").find(recursive=False)
    assert first is not None
    assert first.name == "section"
    assert "Minds in AI." in first.get_text()
    assert "InLoop 编辑部" in first.get_text()


def test_落款区带细线且居中() -> None:
    soup = render("正文。\n", byline="Minds in AI.")
    style = soup.find("section").get("style") or ""
    assert "border-top" in style
    assert "text-align:center" in style


def test_未写落款区则不渲染() -> None:
    result = render_wechat_html(
        normalize_html(render_markdown("正文。\n").html).html,
        config=CONFIG,
        stylesheet=SHEET,
    )
    assert result.has_byline is False
    assert "<section" not in result.html


def test_只有主行时副行不渲染() -> None:
    soup = render("正文。\n", byline="Minds in AI.")
    section = soup.find("section")
    assert len(section.find_all("p")) == 1


def test_落款区函数单独可用() -> None:
    soup = BeautifulSoup("<p>正文</p>", "html.parser")
    assert prepend_byline(soup, byline="刊名") is True
    assert prepend_byline(soup, byline="   ") is False


# --- 重点段落 -------------------------------------------------------------


def test_整段加粗渲染为无卡片的重点段落() -> None:
    """`> **整段话**` 应呈现为主色加粗文字，而不是卡片。"""
    soup = render("> **这一整句是重点**\n")
    blockquote = soup.find("blockquote")
    style = blockquote.get("style") or ""
    assert "transparent" in style, "重点段落不应有卡片底色"
    assert "border-left:none" in style, "重点段落不应有左侧竖线"

    paragraph = blockquote.find("p")
    paragraph_style = paragraph.get("style") or ""
    assert "color:#002fa7" in paragraph_style, "重点段落应为品牌主色"
    assert "font-weight:700" in paragraph_style


def test_普通引用仍是卡片() -> None:
    soup = render("> 这是普通引用\n")
    style = soup.find("blockquote").get("style") or ""
    assert "#f5f7fb" in style
    assert "border-left:3px" in style


def test_引用内局部加粗不触发重点段落() -> None:
    """只有"整段唯一一处加粗"才算重点段落，局部加粗仍应是卡片。"""
    soup = render("> 前一段文字 **局部加粗** 后面的文字\n")
    style = soup.find("blockquote").get("style") or ""
    assert "#f5f7fb" in style


def test_两段引用不触发重点段落() -> None:
    """整段加粗只在"唯一一段且整段加粗"时才算重点，两段引用仍是卡片。"""
    soup = render("> **第一段**\n>\n> 第二段\n")
    style = soup.find("blockquote").get("style") or ""
    assert "#f5f7fb" in style, "两段引用应保留卡片底色"
    assert "background:transparent" not in style


def test_深底引文不受重点段落规则影响() -> None:
    soup = render("> > 引文内容\n")
    blocks = soup.find_all("blockquote")
    inner = blocks[-1]
    assert "#16181d" in (inner.get("style") or "")


def test_重点段落与卡片可同时出现在一篇文章里() -> None:
    soup = render("> **重点**\n\n> 卡片\n")
    blocks = soup.find_all("blockquote")
    assert "transparent" in (blocks[0].get("style") or "")
    assert "#f5f7fb" in (blocks[1].get("style") or "")
