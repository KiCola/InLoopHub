"""一次性检查：任务书经过多轮修订后结构是否仍然完整。

检查项：
- 章节编号连续
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

    # 1. 章节编号
    numbers = [int(m) for m in re.findall(r"(?m)^## (\d+)\.", text)]
    missing = [n for n in range(1, 32) if n not in numbers]
    print(f"章节：找到 {len(numbers)} 个 —— {'✓ 1-31 齐全' if not missing else f'✗ 缺 {missing}'}")
    problems += bool(missing)

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
    stale = {
        "GitHub 仓库是唯一 Source of Truth": "GitHub 仓库是唯一 Source of Truth",
        "以 GitHub 仓库为唯一内容源": "以 GitHub 仓库为唯一内容源",
        "articles/2026/ 路径写法": "articles/2026/",
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
