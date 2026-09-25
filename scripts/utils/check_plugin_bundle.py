"""一次性检查：构建产物里是否真的包含本轮修复的关键代码。

为什么需要：`tsc` 通过只说明类型没问题，不代表产物里含这段逻辑。
本轮两个阻塞修复（预览图片、剪贴板多 flavor）都是运行时行为，
因此要在**打包后的 main.js** 上确认。

注意：esbuild 会把模板字面量里的非 ASCII 转义成 ``\\uXXXX``，
所以直接按中文查找会得到假阴性。这里先还原再查。
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

MAIN_JS = Path(r"E:\InLoopHub\plugin\dist\main.js")


def unescape_js(text: str) -> str:
    """把 ``\\uXXXX`` 还原成字符，便于按中文查找。"""
    return re.sub(r"\\u([0-9A-Fa-f]{4})", lambda m: chr(int(m.group(1), 16)), text)


def main() -> int:
    if not MAIN_JS.is_file():
        print(f"✗ 找不到产物：{MAIN_JS}（先运行 npm run build）")
        return 1

    main_js = unescape_js(MAIN_JS.read_text(encoding="utf-8"))

    checks = {
        "electron.clipboard 写多 flavor": "clipboard.write({ html, text: plain })" in main_js,
        "preview sandbox 用 allow-same-origin": "allow-same-origin" in main_js,
        "已不再使用空 sandbox": 'setAttribute("sandbox", "")' not in main_js,
        "预览插入 <base href>": "<base href=" in main_js,
        "降级时明确提示样式丢失（不静默）": "丢失排版" in main_js and "纯文本" in main_js,
        "状态切换调用 status 命令": '"status"' in main_js,
        "微信发布相关字符串未被打进插件（渲染仍在 Python）": "cgi-bin" not in main_js,
    }

    failed = 0
    for label, ok in checks.items():
        print(f"  {'✓' if ok else '✗'} {label}")
        failed += not ok

    print()
    print("✓ 全部通过" if not failed else f"✗ {failed} 项未通过")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
