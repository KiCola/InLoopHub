"""Obsidian 嵌入语法（``![[图片.png]]``）的支持测试。

## 为什么需要这个功能

作者用 Obsidian 写作，插图最自然的动作是**从剪贴板粘贴**，而 Obsidian 会写成
``![[屏幕截图 2026-09-18 191232.png]]``。markdown-it 只认标准语法
``![](路径)``，于是嵌入会**原样显示成一行文字**，图不出现——而且没有任何报错。

这是实测踩到的：用户的文章里那一行就是原样显示的文字。

## 两个容易漏的点，都有测试守着

1. **路径含空格必须用 ``<...>`` 包起来**。CommonMark 规定未加尖括号的链接目标
   不能含空格，否则整段不被识别为图片。而 Obsidian 粘贴的截图文件名普遍带空格。
2. **HTML 里的 ``src`` 是 URL，不是文件路径**。Markdown 解析器会做百分号编码，
   因此「定位文件」要用解码后的路径、「改写 HTML」要用原样的 URL——
   只用一种形式会让图片既找不到、也改不掉。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from inloop.assets.pipeline import prepare_images  # noqa: E402
from inloop.build import _resolve_embed  # noqa: E402
from inloop.normalize import ExtractedImage, normalize_html  # noqa: E402
from inloop.parser.markdown import (  # noqa: E402
    convert_obsidian_embeds,
    render_markdown,
)

# --- 语法转换 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("![[a.png]]", "![](assets/a.png)"),
        ("![[a.png|说明文字]]", "![说明文字](assets/a.png)"),
        ("![[a.jpg]]", "![](assets/a.jpg)"),
        ("![[a.webp]]", "![](assets/a.webp)"),
        # 尺寸提示放进 title 位置，供渲染层按需使用
        ("![[a.png|300]]", '![](assets/a.png "300")'),
        ("![[a.png|300|说明文字]]", '![说明文字](assets/a.png "300")'),
        # 路径含空格必须加尖括号，否则不会被识别为图片
        ("![[a b.png]]", "![](<assets/a b.png>)"),
        # 中文文件名同样要加尖括号（编码后含 % 但仍以原文判断空格）
        ("![[屏幕 截图.png]]", "![](<assets/屏幕 截图.png>)"),
    ],
)
def test_嵌入语法转标准图片语法(source: str, expected: str) -> None:
    converted, issues = convert_obsidian_embeds(source)
    assert converted == expected
    assert issues == ()


def test_笔记嵌入不被改成图片() -> None:
    """``![[某篇笔记]]`` 没有图片扩展名，必须原样保留。

    误改成图片引用会让读者看到一张坏图，问题比不转换更大。
    """
    converted, issues = convert_obsidian_embeds("![[某篇笔记]]")
    assert converted == "![[某篇笔记]]"
    assert issues == ()


def test_嵌入混在正文中间也能转换() -> None:
    converted, _ = convert_obsidian_embeds("前面 ![[图.png]] 后面")
    assert converted == "前面 ![](assets/图.png) 后面"


def test_找不到图片时产出_ERROR_而不是留下文字() -> None:
    """找不到必须**明确报错**——留一行看不懂的文字是最糟的结果。"""
    converted, issues = convert_obsidian_embeds(
        "![[丢了.png]]", resolve_embed=lambda name: None
    )
    assert "图片缺失" in converted
    assert len(issues) == 1
    assert "IMG105" in issues[0]
    assert "ERROR" in issues[0]


# --- 渲染 -----------------------------------------------------------------


def test_含空格的图片能渲染成_img() -> None:
    """这是本功能的核心：路径含空格时**必须**加尖括号才会被识别为图片。

    不加尖括号时 markdown-it 会原样输出文字——图片静默消失。
    """
    rendered = render_markdown("![[屏幕截图 2026-09-18.png]]")
    assert "<img" in rendered.html, f"没渲染成图片：{rendered.html!r}"
    # src 会被编码成 URL（这是 HTML 的规范行为），因此按"含编码后的片段"判断
    assert "%E5%B1%8F%E5%B9%95" in rendered.html, rendered.html


def test_含空格的英文名也不被拆断() -> None:
    """纯英文带空格的文件名同理：不加尖括号整段不会被当成图片。"""
    rendered = render_markdown("![[my screenshot.png]]")
    assert "<img" in rendered.html, rendered.html
    assert "my%20screenshot.png" in rendered.html, rendered.html


def test_嵌入里的说明文字成为_alt() -> None:
    rendered = render_markdown("![[图.png|示意图]]")
    assert 'alt="示意图"' in rendered.html


def test_中文路径能渲染成_img() -> None:
    rendered = render_markdown("![[架构图.png]]")
    assert "<img" in rendered.html


# --- URL 编码：定位与改写 -------------------------------------------------


def test_解码后的路径用于定位文件() -> None:
    """HTML 里的 src 是 URL；定位文件必须用解码后的路径。"""
    image = ExtractedImage(
        src="assets/%E5%B1%8F%E5%B9%95.png", alt="", title="", is_local=True
    )
    assert image.src == "assets/%E5%B1%8F%E5%B9%95.png"  # 原样保留，用于改写 HTML
    assert image.path == "assets/屏幕.png"  # 解码后的文件路径，用于定位


def test_外链图片解码后不变() -> None:
    image = ExtractedImage(
        src="https://example.com/a%20b.png", alt="", title="", is_local=False
    )
    assert image.path == "https://example.com/a b.png"


def test_含空格与中文的图片能被完整处理(tmp_path: Path) -> None:
    """端到端：正文用嵌入语法 + 文件在 assets/ 子目录 + 名字含空格与中文。

    这条覆盖了实际踩到的全部三个坑：语法不识别、空格导致不成图、
    URL 编码导致找不到文件/改不掉 src。
    """
    article_dir = tmp_path / "001-demo"
    nested = article_dir / "assets" / "index"
    nested.mkdir(parents=True)
    image_name = "屏幕截图 2026-09-18 191232.png"
    Image.new("RGB", (60, 30), (10, 20, 30)).save(nested / image_name)
    # 封面是必填项：缺了会被 IMG003 拦下（那条校验本身是对的）
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(article_dir / "cover.png")
    body = f"![[{image_name}]]\n\n正文。\n"

    # 1) 语法转换 + 渲染：应产出 <img>，src 被百分号编码
    rendered = render_markdown(
        body, resolve_embed=lambda name: _resolve_embed(article_dir, name)
    )
    assert "<img" in rendered.html, rendered.html

    # 2) 规范化：抽出的 src 是 URL 形式，path 是解码后的路径
    normalized = normalize_html(rendered.html)
    assert len(normalized.images) == 1
    image = normalized.images[0]
    assert "%" in image.src or " " not in image.src, "HTML 里的 src 应当是 URL 形式"
    assert image.path.endswith(image_name)

    # 3) 素材管线：能按解码后的路径找到文件并复制
    output_dir = tmp_path / "dist"
    assets = prepare_images(
        article_dir=article_dir,
        output_dir=output_dir,
        images=normalized.images,
        cover="cover.png",
        warning_bytes=10 * 1024 * 1024,
        error_bytes=20 * 1024 * 1024,
    )
    assert not assets.errors, assets.errors
    # 正文图 + 封面
    body_assets = [a for a in assets.assets if a.from_markdown]
    assert len(body_assets) == 1
    # 映射的键必须是 **HTML 里那个原样的字符串**，否则改写时匹配不上
    assert image.src in assets.src_to_output
    assert (output_dir / body_assets[0].output_relative).is_file()


# --- 嵌入解析器 -----------------------------------------------------------


def test_解析器按顺序找图片位置(tmp_path: Path) -> None:
    """嵌入只给文件名，图片可能在文章目录、assets/ 或 assets 的子目录里。"""
    article_dir = tmp_path / "a"
    (article_dir / "assets" / "index").mkdir(parents=True)
    Image.new("RGB", (4, 4)).save(article_dir / "assets" / "index" / "深.png")

    # 直接放文章目录
    Image.new("RGB", (4, 4)).save(article_dir / "平.png")
    assert _resolve_embed(article_dir, "平.png") == "平.png"

    # 在 assets/ 下
    Image.new("RGB", (4, 4)).save(article_dir / "assets" / "常.png")
    assert _resolve_embed(article_dir, "常.png") == "assets/常.png"

    # 在 assets/ 的子目录里（Obsidian 附件目录设置造成的嵌套）
    assert _resolve_embed(article_dir, "深.png") == "assets/index/深.png"

    # 找不到时返回 None，由上层报错
    assert _resolve_embed(article_dir, "没有.png") is None


def test_解析器拒绝路径穿越(tmp_path: Path) -> None:
    """嵌入语法里的 ``../`` 不能让它读到文章目录之外的文件。"""
    article_dir = tmp_path / "a"
    article_dir.mkdir()
    outside = tmp_path / "外.png"
    Image.new("RGB", (4, 4)).save(outside)

    assert _resolve_embed(article_dir, "../外.png") is None
