"""检查仓库文档里的本地链接是否都指向真实存在的文件。

为什么需要它：文档里写了一个不存在的路径，读者点进去是 404，
而且这种错误在纯文本审阅时几乎看不出来。

判定时排除围栏代码块与行内代码——里面的 Markdown 是**示例**，不是真链接。
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: 要检查的文档
DOCUMENTS = (
    "README.md",
    "AGENTS.md",
    "docs/README.md",
    "docs/getting-started.md",
    "docs/architecture.md",
    "docs/content-workflow.md",
    "docs/publishing-guide.md",
    "docs/style-guide.md",
    "docs/roadmap.md",
    "styles/README.md",
    "styles/themes/README.md",
    "articles/README.md",
    "config/README.md",
    "templates/README.md",
    "scripts/README.md",
    "tests/README.md",
)

_LINK = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


def strip_code(text: str) -> str:
    """去掉围栏代码块与行内代码，只留下真正的正文。"""
    lines, fence = [], None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,})", line)
        if marker and fence is None:
            fence = marker.group(1)
            continue
        if marker and fence is not None and len(marker.group(1)) >= len(fence):
            fence = None
            continue
        if fence is None:
            lines.append(line)
    return re.sub(r"`[^`\n]*`", "``", "\n".join(lines))


def main() -> int:
    broken: list[str] = []
    checked = 0

    for name in DOCUMENTS:
        document = REPO_ROOT / name
        if not document.is_file():
            broken.append(f"{name}：文档本身不存在")
            continue
        content = strip_code(document.read_text(encoding="utf-8"))
        for label, target in _LINK.findall(content):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path_part = target.split("#")[0]
            if not path_part:
                continue
            checked += 1
            if not (document.parent / path_part).exists():
                broken.append(f"{name}：[{label}]({target})")

    print(f"检查了 {len(DOCUMENTS)} 个文档、{checked} 个本地链接")
    if broken:
        print("失效链接：")
        for item in broken:
            print(f"  ✗ {item}")
        return 1
    print("✓ 全部有效")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
