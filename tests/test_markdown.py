"""Markdown 渲染与结构规范化的测试（任务书 §22）。

覆盖重点：Markdown→HTML、代码块、表格、中文标题、Unicode、GIF、
脚注与公式的降级、以及产物中不允许出现的标签是否真的被清掉。
"""

from __future__ import annotations

from inloop.normalize import normalize_html
from inloop.parser.markdown import render_markdown


def render(text: str) -> str:
    """走完整链路：渲染 → 规范化。"""
    return normalize_html(render_markdown(text).html).html


# --- 基础转换 -------------------------------------------------------------


def test_标题与段落() -> None:
    html = render("# 一级\n\n## 二级\n\n一段正文。\n")
    assert "<h1>一级</h1>" in html
    assert "<h2>二级</h2>" in html
    assert "<p>一段正文。</p>" in html


def test_中文标题与_Unicode_不被破坏() -> None:
    html = render("# Light-O1：20Hz 到底意味着什么？\n")
    assert "Light-O1：20Hz 到底意味着什么？" in html


def test_强调与行内代码() -> None:
    html = render("**粗** *斜* `code` ~~删~~\n")
    assert "<strong>粗</strong>" in html
    assert "<em>斜</em>" in html
    assert "<code>code</code>" in html
    assert "<s>删</s>" in html


def test_表格() -> None:
    html = render("| A | B |\n|---|---|\n| 1 | 2 |\n")
    assert "<table>" in html
    assert "<th>A</th>" in html
    assert "<td>1</td>" in html


def test_代码块保留语言标记() -> None:
    html = render("```python\ndef f():\n    return 1\n```\n")
    assert "<pre>" in html
    # 语言标记是语义信息，渲染层要靠它选语法着色器，不能在规范化阶段被清掉
    assert "language-python" in html


def test_引用与分割线() -> None:
    html = render("> 引用\n\n---\n")
    assert "<blockquote>" in html
    assert "<hr" in html


def test_列表() -> None:
    html = render("- 甲\n- 乙\n\n1. 一\n2. 二\n")
    assert "<ul>" in html and "<ol>" in html
    assert "<li>甲</li>" in html


def test_外链保留_href() -> None:
    html = render("[站点](https://example.com)\n")
    assert 'href="https://example.com"' in html


def test_图片保留_src_与_alt() -> None:
    html = render('![架构图](assets/a.png "图注")\n')
    assert 'src="assets/a.png"' in html
    assert 'alt="架构图"' in html


def test_GIF_与普通图片同样处理() -> None:
    html = render("![动画](assets/loop.gif)\n")
    assert 'src="assets/loop.gif"' in html


# --- 降级：微信端无法成立的两类语法 ---------------------------------------


def test_脚注降级为文末注释列表() -> None:
    result = normalize_html(render_markdown("正文[^1]\n\n[^1]: 注释内容\n").html)
    assert result.footnote_count == 1
    # 锚点跳转在微信端不可用，因此不应残留 href="#fn1"
    assert 'href="#fn1"' not in result.html
    assert "注释" in result.html
    assert "[1]" in result.html
    assert any("脚注" in w for w in result.warnings)


def test_行内公式降级为等宽文本() -> None:
    result = normalize_html(render_markdown("公式 $E = mc^2$ 结束。\n").html)
    assert result.math_count == 1
    assert "E = mc^2" in result.html
    assert "math inline" not in result.html
    assert any("公式" in w for w in result.warnings)


def test_块级公式降级为代码块() -> None:
    result = normalize_html(render_markdown("$$\n\\frac{a}{b}\n$$\n").html)
    assert result.math_count == 1
    assert "\\frac{a}{b}" in result.html


def test_任务列表复选框降级为文本标记() -> None:
    """input 是表单元素，微信正文不支持；若不先转文本就清洗，完成状态会丢失。"""
    result = normalize_html(render_markdown("- [x] 已完成\n- [ ] 未完成\n").html)
    assert "<input" not in result.html
    assert "☑" in result.html
    assert "☐" in result.html
    assert any("任务列表" in w or "复选框" in w for w in result.warnings)


# --- 白名单清洗 -----------------------------------------------------------


def test_危险标签被整体删除() -> None:
    html = normalize_html(
        '<p>正常</p><script>alert(1)</script><iframe src="x"></iframe>'
    ).html
    assert "<script" not in html
    assert "<iframe" not in html
    assert "alert" not in html
    assert "正常" in html


def test_未知标签被解开但保留文字() -> None:
    html = normalize_html("<p>前<mark>标记文字</mark>后</p>").html
    assert "<mark" not in html
    assert "标记文字" in html


def test_剥离_id_与_class() -> None:
    html = normalize_html('<p id="x" class="y">文字</p>').html
    assert "id=" not in html
    assert "class=" not in html
    assert "文字" in html


def test_保留链接与图片的必要属性() -> None:
    html = normalize_html(
        '<p><a href="https://e.com" id="a">链接</a>'
        '<img src="a.png" alt="图" title="注" class="c"></p>'
    ).html
    assert 'href="https://e.com"' in html
    assert 'src="a.png"' in html
    assert 'alt="图"' in html
    assert "id=" not in html and "class=" not in html


# --- 空与边界 -------------------------------------------------------------


def test_空正文不报错() -> None:
    result = render_markdown("")
    assert result.html == ""
    assert result.warnings == ()


def test_未闭合代码块按代码块渲染且不抛异常() -> None:
    """围栏未闭合时 markdown-it 仍会渲染成代码块，不应抛异常。"""
    html = render("```python\ndef f():\n")
    assert "<pre>" in html
    assert "def f():" in html


def test_中文与英文混排不产生乱码() -> None:
    html = render("中文 English 混排，缩写 EAI 与 URL https://example.com 共存。\n")
    assert "中文 English" in html
    assert "EAI" in html
