"""一次性检查：任务书经过多轮修订后结构是否仍然完整。

检查项：
- 章节编号连续（顶层 `## N.` 与子节 `### N.M`）
- 围栏代码块成对
- 关键改动确实写进去了
- 没有残留的过时表述
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FENCE = "`" * 3

#: 顶层章节应覆盖的编号范围
TOP_LEVEL_RANGE = range(1, 32)

#: 子节中**必须存在**的（新增功能必须在任务书里有依据，
#: 否则按 AGENTS.md 第 6 行"需求只从任务书取"，实现就成了无据可依）
REQUIRED_SUBSECTIONS = ("7.3", "7.4", "7.5")


def main() -> int:
    books = sorted(REPO_ROOT.glob("*任务书*.md"))
    if not books:
        print("✗ 没找到任务书")
        return 1
    book = books[0]
    text = book.read_text(encoding="utf-8")

    print(f"文件：{book.name}")
    print(f"行数：{len(text.splitlines())}")
    print()

    problems = 0

    # 1. 顶层章节编号
    numbers = [int(m) for m in re.findall(r"(?m)^## (\d+)\.", text)]
    missing = [n for n in TOP_LEVEL_RANGE if n not in numbers]
    verdict = "✓ 1-31 齐全" if not missing else f"✗ 缺 {missing}"
    print(f"顶层章节：找到 {len(numbers)} 个 —— {verdict}")
    problems += bool(missing)

    # 1b. 新增功能的子节必须有依据
    subsections = set(re.findall(r"(?m)^### (\d+\.\d+)", text))
    missing_subs = [s for s in REQUIRED_SUBSECTIONS if s not in subsections]
    present = "、".join(REQUIRED_SUBSECTIONS)
    verdict = f"✓ {present} 存在" if not missing_subs else f"✗ 缺 {missing_subs}"
    print(f"必需子节：{verdict}")
    problems += bool(missing_subs)

    # 2. 代码块成对
    fences = len(re.findall(rf"(?m)^{FENCE}", text))
    paired = fences % 2 == 0
    print(f"围栏代码块：{fences} 个 —— {'✓ 成对' if paired else '✗ 有未闭合'}")
    problems += not paired

    print()

    # 3. 关键改动
    expected = {
        "内容目录是唯一事实源": "内容目录是唯一事实源",
        "content_root 解析顺序": "content_root 的解析顺序",
        "索引改为 INDEX.md": "INDEX.md 中的文章索引区块",
        "Actions 已取消": "本节已取消",
        "微信实测结论": "实测结论",
        "示例文章挪到 examples/": "examples/",
        "修订记录": "修订记录",
    }
    print("关键改动：")
    for label, needle in expected.items():
        found = needle in text
        print(f"  {'✓' if found else '✗'} {label}")
        problems += not found

    print()

    # 4. 过时表述
    # 注：修订记录里出现 "示例文章原在 `articles/`" 是**正确的历史记录**，
    # 因此这里只查会把读者引向错误路径的表述（形如 ``articles/2026/``），
    # 而不是一律禁止 "articles" 字样。
    stale = {
        "GitHub 仓库是唯一 Source of Truth": "GitHub 仓库是唯一 Source of Truth",
        "以 GitHub 仓库为唯一内容源": "以 GitHub 仓库为唯一内容源",
        "把兜底内容目录写成 articles/": "articles/2026/",
        "requirements.txt": "requirements.txt",
        "索引写在 README.md": "README.md 中的文章索引",
    }
    print("过时表述（应全部不存在）：")
    for label, needle in stale.items():
        found = needle in text
        print(f"  {'✗ 仍存在' if found else '✓ 已清理'} {label}")
        problems += found

    print()
    print("✓ 全部通过" if not problems else f"✗ 有 {problems} 项问题")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
