"""排版主题与文件写入工具的测试。

主题是本项目"样式与代码解耦"的关键：主题文件只描述节奏，共用部分在 base。
这里固定住几个容易回归的点：所有主题都能加载、必须带 base 的变量、
深底卡片在每个主题下都要生效、未知主题要报出可用清单。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from inloop.config import load_config
from inloop.fsutil import write_bytes, write_text
from inloop.normalize import normalize_html
from inloop.parser.markdown import render_markdown
from inloop.renderer.wechat import (
    DEFAULT_THEME,
    StyleError,
    available_themes,
    load_stylesheet,
    render_wechat_html,
    theme_name,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
CONFIG = load_config(REPO_ROOT)

#: 本仓库提供的主题。新增主题时同步更新，以便每个主题都被测试到。
EXPECTED_THEMES = ("compact", "generous", "inloop", "standard")

#: 浅底卡片与深底卡片对应的背景色（来自 styles/base.css 的变量）
LIGHT_CARD_BG = "#f5f7fb"
DARK_CARD_BG = "#16181d"


def render_cards(theme: str) -> str:
    body = normalize_html(render_markdown("> 浅底\n\n> > 深底\n").html).html
    return render_wechat_html(
        body, config=CONFIG, stylesheet=load_stylesheet(CONFIG, theme)
    ).html


def test_主题清单与预期一致() -> None:
    assert available_themes(CONFIG) == EXPECTED_THEMES


def test_默认主题存在() -> None:
    assert DEFAULT_THEME in available_themes(CONFIG)


@pytest.mark.parametrize("theme", EXPECTED_THEMES)
def test_每个主题都能加载并解析出规则(theme: str) -> None:
    sheet = load_stylesheet(CONFIG, theme)
    assert sheet.rules, f"主题 {theme} 解析出 0 条规则"
    # base.css 定义的变量必须可用，否则主题里 var(--brand-primary) 会失效
    assert "--brand-primary" in sheet.variables
    assert sheet.container_declarations(), f"主题 {theme} 未提供容器样式"


@pytest.mark.parametrize("theme", EXPECTED_THEMES)
def test_每个主题的浅底与深底卡片都生效(theme: str) -> None:
    """两种卡片是互斥选择器，曾因主题里给通用 blockquote 写 background 而失效。"""
    html = render_cards(theme)
    assert LIGHT_CARD_BG in html, f"{theme}：浅底卡片未生效"
    assert DARK_CARD_BG in html, f"{theme}：深底卡片未生效"


@pytest.mark.parametrize("theme", EXPECTED_THEMES)
def test_每个主题都产出零_class_的内联样式(theme: str) -> None:
    body = normalize_html(render_markdown("# 标题\n\n正文。\n").html).html
    html = render_wechat_html(
        body, config=CONFIG, stylesheet=load_stylesheet(CONFIG, theme)
    ).html
    assert "class=" not in html
    assert 'style="' in html


def test_主题覆盖基础样式() -> None:
    """主题文件后加载，应当覆盖 base 的同名属性。"""
    compact = load_stylesheet(CONFIG, "compact").container_declarations()
    generous = load_stylesheet(CONFIG, "generous").container_declarations()
    assert compact["line-height"] != generous["line-height"]
    # 慷慨主题行高更大
    assert float(generous["line-height"].rstrip("px")) > float(
        compact["line-height"].rstrip("px")
    )


def test_默认主题取_紧凑的标题与标准的卡片() -> None:
    """inloop 主题是两套候选的合成，这里固定住这个组合。

    - 标题：主色下划线（取自 compact）
    - 浅底卡片：圆角且无左侧竖线（取自 standard）
    """
    body = normalize_html(render_markdown("# 标题\n\n> 卡片\n").html).html
    html = render_wechat_html(
        body, config=CONFIG, stylesheet=load_stylesheet(CONFIG, "inloop")
    ).html

    h1 = re.search(r"<h1 style=\"([^\"]*)\"", html)
    assert h1 is not None
    assert "border-bottom" in h1.group(1), "默认主题的标题应带下划线"

    card = re.search(r"<blockquote style=\"([^\"]*)\"", html)
    assert card is not None
    assert "border-radius" in card.group(1), "默认主题的卡片应为圆角"
    assert "border-left" not in card.group(1), "默认主题的卡片不应有左侧竖线"


def test_未知主题报出可用清单() -> None:
    with pytest.raises(StyleError, match="compact"):
        load_stylesheet(CONFIG, "no-such-theme")


def test_主题名取自配置() -> None:
    from inloop.config import Config

    assert theme_name(CONFIG) == CONFIG.wechat_value("theme")

    # 缺 theme 键时退回默认主题，而不是崩溃
    partial = Config(
        root=CONFIG.root, site=CONFIG.site, brand=CONFIG.brand, wechat={"font_size": 16}
    )
    assert theme_name(partial) == DEFAULT_THEME


def test_主题不含无法内联的选择器() -> None:
    """所有主题都必须能被完整内联，否则构建会在运行时才失败。"""
    for theme in EXPECTED_THEMES:
        load_stylesheet(CONFIG, theme)  # 不抛异常即通过


# --- 文件写入 -------------------------------------------------------------


def test_写文本使用_LF(tmp_path: Path) -> None:
    target = tmp_path / "a" / "note.md"
    write_text(target, "第一行\n第二行\n")
    assert target.read_bytes() == "第一行\n第二行\n".encode()
    assert b"\r\n" not in target.read_bytes()


def test_写文本会创建父目录(tmp_path: Path) -> None:
    target = tmp_path / "deep" / "nested" / "file.txt"
    write_text(target, "内容")
    assert target.is_file()


def test_写文本覆盖已有内容(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    write_text(target, "旧内容")
    write_text(target, "新内容")
    assert target.read_text(encoding="utf-8") == "新内容"


def test_写二进制(tmp_path: Path) -> None:
    target = tmp_path / "blob.bin"
    payload = bytes(range(256))
    write_bytes(target, payload)
    assert target.read_bytes() == payload


def test_写入不留下临时文件(tmp_path: Path) -> None:
    target = tmp_path / "file.txt"
    write_text(target, "内容")
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "file.txt"]
    assert leftovers == [], f"残留临时文件：{leftovers}"


def test_写入失败时清理临时文件(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """替换失败时必须清掉临时文件，否则仓库里会慢慢堆满半截文件。"""
    import inloop.fsutil as fsutil

    def boom(source: Path, target: Path) -> None:
        raise PermissionError("模拟目标被占用")

    monkeypatch.setattr(fsutil, "_replace_with_retry", boom)
    with pytest.raises(PermissionError):
        write_text(tmp_path / "file.txt", "内容")

    leftovers = [p.name for p in tmp_path.iterdir()]
    assert leftovers == [], f"失败后残留：{leftovers}"
