"""一次性核对：产物里代码块的文本，是否与源 Markdown 里的代码块逐字符一致。

为什么需要它：代码块的空白曾经在构建中被吃掉（词间空格粘连、缩进消失），
而"看起来差不多"是发现不了这种问题的——必须逐字符比对。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from inloop.renderer.wechat import _restore_code_spaces  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]
FENCE = "`" * 3


def source_blocks(markdown: str) -> list[str]:
    """取出源 Markdown 里所有围栏代码块的内容。"""
    pattern = re.compile(rf"{FENCE}[^\n]*\n(.*?){FENCE}", re.DOTALL)
    return [match.group(1) for match in pattern.finditer(markdown)]


def product_blocks(html: str) -> list[str]:
    """取出产物里**代码块**的文本，并还原空格哨兵。

    产物里有两种 ``<pre>``，都含 ``<code>``，靠内容判据区分不可靠。
    真正稳定的区别是 ``white-space:pre`` 写在哪一层：

    - 代码块：写在 ``<code>`` 上（样式表里定义的），``<pre>`` 自己没有该属性
    - 被降级的公式块（规则 MD103）：写在 ``<pre>`` 自己身上（降级时直接给的）

    因此判据是"``<pre>`` 自身不带 ``white-space:pre``"。否则公式块会被误当成
    代码块，报出"数量不一致"这种假问题。
    """
    soup = BeautifulSoup(html, "html.parser")
    blocks: list[str] = []
    for pre in soup.find_all("pre"):
        if "white-space:pre" in (pre.get("style") or ""):
            continue
        blocks.append(_restore_code_spaces(pre.get_text()))
    return blocks


def find_article_indexes() -> list[Path]:
    """找出要核对的文章（按内容目录顺序）。

    内容与工具解耦后，仓库里能出现文章的地方有两处：

    - ``content/``：``content_root`` 的兜底位置（本机未配置时文章写在这里），
      被 ``.gitignore`` 排除，因此 clone 下来通常是空的
    - ``examples/``：随仓库分发的排版示例，测试与演示用

    两处都扫，避免"只认一个目录"导致删掉示例后脚本还去找不存在的文件
    （这正是上一版的问题）。
    """
    found: list[Path] = []
    for base in (REPO_ROOT / "content", REPO_ROOT / "examples"):
        if not base.is_dir():
            continue
        for year in sorted(p for p in base.iterdir() if p.is_dir()):
            found.extend(sorted(year.glob("[0-9]*-*/index.md")))
    return found


def main() -> int:
    index_files = find_article_indexes()
    if not index_files:
        print("✗ 在 content/ 与 examples/ 下都没有找到文章")
        return 1

    failures = 0
    checked = 0
    for index in index_files:
        slug = index.parent.name
        product = REPO_ROOT / "dist/wechat" / slug / "article.html"
        if not product.is_file():
            # 未构建是正常状态（产物不入库），不算失败
            print(f"跳过 {slug}（尚未构建，先跑 inloop build-wechat）")
            continue

        markdown = index.read_text(encoding="utf-8")
        # 去掉 front matter 后只取正文里的围栏代码块
        source = source_blocks(markdown.split("---", 2)[-1])
        built = product_blocks(product.read_text(encoding="utf-8"))

        if not source:
            print(f"跳过 {slug}（源文件没有代码块）")
            continue

        checked += 1
        if len(source) != len(built):
            print(f"✗ {slug}: 代码块数量不一致 源 {len(source)} / 产物 {len(built)}")
            failures += 1
            continue

        mismatched = [
            (number, want, got)
            for number, (want, got) in enumerate(zip(source, built, strict=True), start=1)
            if want != got
        ]
        if mismatched:
            failures += 1
            for number, want, got in mismatched:
                print(f"✗ {slug} 第 {number} 个代码块：产物与源不一致")
                print(f"   源  : {want[:80]!r}")
                print(f"   产物: {got[:80]!r}")
            continue

        indents = sorted(
            {
                len(line) - len(line.lstrip(" "))
                for block in built
                for line in block.splitlines()
                if line.strip()
            }
        )
        print(f"✓ {slug}: {len(built)} 个代码块逐字符一致，缩进集合 {indents}")

    if checked == 0:
        print("✗ 没有可校验的文章（都需要先构建）")
        return 1
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
