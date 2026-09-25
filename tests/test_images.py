"""图片处理与微信渲染的测试（任务书 §22）。

覆盖重点：图片路径、inline CSS、代码块、表格、不存在图片、体积阈值、
零 class、以及构建产物的完整性。
"""

from __future__ import annotations

from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from PIL import Image

from inloop.assets.pipeline import SUPPORTED_SUFFIXES, image_size, prepare_images
from inloop.config import load_config
from inloop.normalize import ExtractedImage, normalize_html
from inloop.parser.markdown import render_markdown
from inloop.renderer.wechat import StyleError, load_stylesheet, parse_css, render_wechat_html

# --- 图片尺寸解析 ---------------------------------------------------------


@pytest.mark.parametrize("suffix", [".png", ".jpg", ".gif"])
def test_读取图片尺寸(tmp_path: Path, suffix: str) -> None:
    path = tmp_path / f"pic{suffix}"
    Image.new("RGB", (320, 200), (1, 2, 3)).save(path)
    assert image_size(path) == (320, 200)


def test_非图片文件返回_None(tmp_path: Path) -> None:
    path = tmp_path / "not_image.png"
    path.write_bytes(b"this is not an image at all")
    assert image_size(path) is None


def test_支持格式清单符合任务书() -> None:
    assert SUPPORTED_SUFFIXES == {".png", ".jpg", ".jpeg", ".gif", ".webp"}


# --- 素材流水线 -----------------------------------------------------------


def _prepare(tmp_path: Path, images: tuple[ExtractedImage, ...], cover: str = "cover.png", **kw):
    article_dir = tmp_path / "article"
    (article_dir / "assets").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (100, 60), (9, 9, 9)).save(article_dir / "cover.png")
    return prepare_images(
        article_dir=article_dir,
        output_dir=tmp_path / "out",
        images=images,
        cover=cover,
        warning_bytes=kw.get("warning_bytes", 3 * 1024 * 1024),
        error_bytes=kw.get("error_bytes", 8 * 1024 * 1024),
    )


def test_图片不存在报_ERROR(tmp_path: Path) -> None:
    result = _prepare(tmp_path, (ExtractedImage("assets/none.png", "图", "", True),))
    assert not result.ok
    assert any("IMG001" in e for e in result.errors)


def test_格式不受支持报_ERROR(tmp_path: Path) -> None:
    (tmp_path / "article" / "assets").mkdir(parents=True, exist_ok=True)
    (tmp_path / "article" / "assets" / "a.bmp").write_bytes(b"BM")
    result = _prepare(tmp_path, (ExtractedImage("assets/a.bmp", "图", "", True),))
    assert any("IMG004" in e for e in result.errors)


def test_绝对路径报_ERROR(tmp_path: Path) -> None:
    result = _prepare(tmp_path, (ExtractedImage("C:\\x\\a.png", "图", "", True),))
    assert any("IMG002" in e for e in result.errors)


def test_缺_alt_报_WARNING(tmp_path: Path) -> None:
    (tmp_path / "article" / "assets").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (50, 50), (1, 1, 1)).save(tmp_path / "article" / "assets" / "a.png")
    result = _prepare(tmp_path, (ExtractedImage("assets/a.png", "", "注", True),))
    assert any("IMG101" in w for w in result.warnings)


def test_外部图片不复制(tmp_path: Path) -> None:
    result = _prepare(
        tmp_path, (ExtractedImage("https://example.com/a.png", "图", "注", False),)
    )
    assert result.ok
    assert result.src_to_output == {}
    assert all(a.from_markdown is False for a in result.assets)  # 只剩封面


def test_同一图片多次引用只复制一次(tmp_path: Path) -> None:
    (tmp_path / "article" / "assets").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (50, 50), (1, 1, 1)).save(tmp_path / "article" / "assets" / "a.png")
    result = _prepare(
        tmp_path,
        (
            ExtractedImage("assets/a.png", "图一", "注", True),
            ExtractedImage("assets/a.png", "图二", "注", True),
        ),
    )
    markdown_assets = [a for a in result.assets if a.from_markdown]
    assert len(markdown_assets) == 1
    assert result.src_to_output["assets/a.png"] == "images/a.png"


def test_同名图片冲突报_ERROR(tmp_path: Path) -> None:
    """产物目录是平铺的，同名会互相覆盖，必须报错而不是静默改名。"""
    assets_dir = tmp_path / "article" / "assets"
    (assets_dir / "sub").mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (10, 10), (1, 1, 1)).save(assets_dir / "a.png")
    Image.new("RGB", (10, 10), (2, 2, 2)).save(assets_dir / "sub" / "a.png")

    result = _prepare(
        tmp_path,
        (
            ExtractedImage("assets/a.png", "一", "注", True),
            ExtractedImage("assets/sub/a.png", "二", "注", True),
        ),
    )
    assert any("冲突" in e for e in result.errors)


def test_封面缺失报_ERROR(tmp_path: Path) -> None:
    (tmp_path / "article").mkdir(parents=True, exist_ok=True)
    result = _prepare(tmp_path, (), cover="missing.png")
    assert any("IMG003" in e for e in result.errors)


def test_封面被复制到产物根(tmp_path: Path) -> None:
    result = _prepare(tmp_path, ())
    assert (tmp_path / "out" / "cover.png").is_file()
    assert any(a.output_relative == Path("cover.png") for a in result.assets)


# --- CSS 解析 -------------------------------------------------------------


def test_解析_CSS_并解析变量() -> None:
    sheet = parse_css(":root { --c: #123456; } p { color: var(--c); }")
    assert sheet.variables["--c"] == "#123456"
    # 变量必须被解析为字面值：微信端不保证支持 CSS 变量
    assert sheet.rules[0][1]["color"] == "#123456"


def test_无法内联的选择器报错() -> None:
    for selector in ("p:hover", "p::before", "#id"):
        with pytest.raises(StyleError):
            parse_css(f"{selector} {{ color: red; }}")


def test_容器类名被忽略() -> None:
    sheet = parse_css(".inloop-article p { margin: 0; }")
    assert sheet.rules[0][0] == "p"


# --- 渲染 -----------------------------------------------------------------


def test_样式全部内联且零_class() -> None:
    sheet = load_stylesheet(load_config())
    result = render_wechat_html("<h1>标题</h1><p>正文</p>", config=load_config(), stylesheet=sheet)
    assert "class=" not in result.html
    assert 'style="' in result.html
    assert "<h1 style=" in result.html
    assert "<p style=" in result.html


def test_产物不含_script_与_style_标签() -> None:
    sheet = load_stylesheet(load_config())
    html = render_wechat_html(
        "<p>文字</p>", config=load_config(), stylesheet=sheet
    ).html
    assert "<script" not in html
    assert "<style" not in html


def test_图片说明按_title_生成() -> None:
    sheet = load_stylesheet(load_config())
    html = render_wechat_html(
        '<p><img src="a.png" alt="说明" title="图 1" /></p>',
        config=load_config(),
        stylesheet=sheet,
    ).html
    assert "图 1" in html
    # 图注必须自带样式：产物零 class，靠选择器会失效
    assert html.count("text-align:center") >= 1


def test_图片强制最大宽度() -> None:
    sheet = load_stylesheet(load_config())
    html = render_wechat_html(
        '<p><img src="a.png" alt="x" /></p>', config=load_config(), stylesheet=sheet
    ).html
    assert "max-width:100%" in html


def test_未匹配样式的标签会被报告() -> None:
    sheet = load_stylesheet(load_config())
    result = render_wechat_html(
        "<figcaption>说明</figcaption>", config=load_config(), stylesheet=sheet
    )
    assert "figcaption" in result.unstyled_tags


def test_正文容器带样式() -> None:
    """容器自身的基础排版样式必须写到它的 style 上。

    容器的 CSS 规则写作 ``.inloop-article``，而规范化后的选择器是空字符串
    （容器类名不参与元素匹配），曾因此整段基础样式（字号、行高、颜色、字体族）
    被静默丢弃。这里把该行为固定住。
    """
    from bs4 import BeautifulSoup

    config = load_config()
    sheet = load_stylesheet(config)
    styles = sheet.container_declarations()
    assert "font-size" in styles
    assert "line-height" in styles
    assert "font-family" in styles
    # 值中不应残留换行：内联样式里的换行只会让产物变脏
    assert not any("\n" in value for value in styles.values())

    html = render_wechat_html("<p>正文</p>", config=config, stylesheet=sheet).html
    container = BeautifulSoup(html, "html.parser").find("div")
    assert container is not None
    assert container.get("style"), "正文容器必须带内联样式"


def test_正文容器内的元素全部带样式() -> None:
    """任务书 §9.2：样式必须内联，否则粘进编辑器会整段失效。"""
    from bs4 import BeautifulSoup

    config = load_config()
    sheet = load_stylesheet(config)
    html = render_wechat_html(
        "<h1>标题</h1><p>文字<strong>粗</strong></p>"
        "<blockquote><p>引用</p></blockquote>"
        "<table><tr><th>甲</th></tr><tr><td>乙</td></tr></table>"
        "<pre><code>x = 1</code></pre>"
        '<p><img src="a.png" alt="图" /></p>',
        config=config,
        stylesheet=sheet,
    ).html

    container = BeautifulSoup(html, "html.parser").find("div")
    assert container is not None
    structural = {"br", "hr", "thead", "tbody", "tr"}
    missing = [
        tag.name
        for tag in container.find_all(True)
        if tag.name not in structural and not tag.get("style")
    ]
    assert missing == [], f"这些标签缺少内联样式：{missing}"


def test_已带内联样式的标签不算漏样式() -> None:
    """语法着色生成的 token span 样式来自 Pygments，不能报成"样式漏了"。"""
    sheet = load_stylesheet(load_config())
    result = render_wechat_html(
        '<pre><code><span style="color:red;">x</span></code></pre>',
        config=load_config(),
        stylesheet=sheet,
    )
    assert "span" not in result.unstyled_tags


def _code_text(html: str) -> str:
    """取出代码块的纯文本，并把空格哨兵还原。

    代码块里的空格在构建期间会被换成私有使用区哨兵（防止 HTML 解析器折叠
    连续空格导致缩进丢失），最终产物字符串里已还原；这里从 HTML 再解析一次时
    需要自己还原，否则看到的是一串哨兵字符。
    """
    from inloop.renderer.wechat import _restore_code_spaces

    pre = BeautifulSoup(html, "html.parser").find("pre")
    return _restore_code_spaces(pre.get_text())


def test_代码块保留缩进与词间空格() -> None:
    """代码块的空白必须逐字符保留。

    这条回归测试来自一次真实事故：产物在自己的预览里看着正常，但粘进微信后
    `from dataclasses import` 变成 `from dataclassesimport`、缩进整段消失，
    示例代码直接变成语法错误。

    根因：BeautifulSoup 的 html.parser 会在**解析阶段**把元素内部的连续空格
    折叠成一个（换行不受影响），而缩进恰好就是连续空格。
    """
    source = (
        "```python\n"
        "from dataclasses import dataclass\n"
        "class Stage:\n"
        "    name: str\n"
        "\n"
        "    def digest(self) -> str:\n"
        "        return 'x'\n"
        "```\n"
    )
    html = normalize_html(render_markdown(source).html).html
    result = render_wechat_html(
        html, config=load_config(), stylesheet=load_stylesheet(load_config())
    )
    text = _code_text(result.html)

    assert "from dataclasses import dataclass" in text, "词间空格被折叠了"
    indents = {
        len(line) - len(line.lstrip(" ")) for line in text.splitlines() if line.strip()
    }
    assert 4 in indents and 8 in indents, f"缩进丢失，实际缩进集合 {indents}"
    # 保护空白用的哨兵字符绝不能泄漏到产物里
    assert "\ue000" not in result.html
    # 保住空白不能以牺牲着色为代价
    assert "color:#" in result.html


def test_无语言标识的代码块同样保留缩进() -> None:
    """没有语言标识时不语法着色，但缩进依然不能丢。"""
    source = "```\nplain   text\n    indented\n```\n"
    html = normalize_html(render_markdown(source).html).html
    result = render_wechat_html(
        html, config=load_config(), stylesheet=load_stylesheet(load_config())
    )
    assert "    indented" in _code_text(result.html), "无语言标识时缩进也不该丢"
