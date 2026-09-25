"""pytest 共享夹具。

设计原则：**夹具从仓库真实文件派生，不复制一份。**

任务书 §28 明确要求用真实中文技术文章验证，因为"测试页面很好看、真正技术文章
一塌糊涂"。若把文章再拷一份到 `tests/fixtures/`，两份副本必然漂移——真正被验证的
就不再是仓库里的那些文章了。因此这里只构造**最小可运行的临时仓库**，
以及供各测试用例改造的**最小合法文章文本**。
"""

from __future__ import annotations

import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]

# 临时目录的根由 pyproject.toml 的 --basetemp 指定为工作区内的 .pytest_tmp/。
# 这里不额外做路径推断：本机环境中 tempfile.gettempdir() 不可靠（会回退到
# 当前工作目录），推断逻辑反而会掩盖真实位置。

#: 最小合法文章的正文（各测试在此基础上增删字段）
MINIMAL_BODY = """# 测试标题

> TL;DR：一段引用。

正文含 **加粗**、*斜体*、`行内代码`、[外链](https://example.com)。

| 列A | 列B |
|---|---|
| 1 | 2 |

```python
def f(x):
    return x + 1
```

![示意图](assets/pic.png "图 1：示意")

---

~~删除线~~ 与普通文字[^1]。

[^1]: 脚注内容。

行内公式 $E = mc^2$。
"""

MINIMAL_FRONT = """---
id: 7
title: "测试文章"
slug: "test-article"
date: 2026-09-25
author: "测试作者"
category: "research"
status: "draft"
tags:
  - 标签一
  - 标签二
summary: "一句话摘要。"
cover: "cover.png"
byline: "测试刊名"
byline_note: "测试副题"
platforms:
  wechat: true
  blog: false
---
"""


def make_article_text(front: str = MINIMAL_FRONT, body: str = MINIMAL_BODY) -> str:
    """拼出一篇完整文章文本。"""
    return f"{front}\n{body}"


@pytest.fixture()
def article_text() -> str:
    """最小合法文章文本。"""
    return make_article_text()


@pytest.fixture()
def mini_repo(tmp_path: Path) -> Iterator[Path]:
    """构造一个最小可运行仓库。

    复制真实的 ``styles/``、``config/``、``templates/`` 与 ``pyproject.toml``：
    这些都是构建的必要输入，且必须用真实版本，否则测的就不是真实行为。
    """
    for name in ("styles", "config", "templates"):
        shutil.copytree(REPO_ROOT / name, tmp_path / name)
    shutil.copy2(REPO_ROOT / "pyproject.toml", tmp_path / "pyproject.toml")
    (tmp_path / "articles" / "2026").mkdir(parents=True)
    yield tmp_path


@pytest.fixture()
def mini_article(mini_repo: Path) -> tuple[Path, str]:
    """在最小仓库中写入一篇文章，返回 (index.md 路径, 文章文本)。

    返回 **index.md 的路径**而不是文章目录：调用方几乎总是要读这个文件来
    构造 :class:`Article`，返回目录会迫使每个调用方自己拼 `/ "index.md"`。
    需要目录时用 ``index.parent``。
    """
    from PIL import Image

    article_dir = mini_repo / "articles" / "2026" / "007-test-article"
    (article_dir / "assets").mkdir(parents=True)
    Image.new("RGB", (600, 300), (0, 47, 167)).save(article_dir / "assets" / "pic.png")
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(article_dir / "cover.png")

    text = make_article_text()
    index = article_dir / "index.md"
    index.write_text(text, encoding="utf-8", newline="\n")
    return index, text
