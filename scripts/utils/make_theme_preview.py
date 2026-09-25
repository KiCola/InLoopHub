"""生成排版主题对照页（一次性比较工具，不参与运行时）。

用途：把同一段示例内容用全部主题各渲染一份，并排放在一个本地 HTML 里，
用浏览器直接对比观感、选定主题。选定后把 config/wechat.yaml 的 theme 改掉即可。

放在 scripts/utils/ 下而不是包内：它只服务"挑主题"这个一次性动作。

用法：python scripts/utils/make_theme_preview.py
输出：dist/theme-compare.html
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"
if SRC.is_dir() and str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from inloop.config import load_config  # noqa: E402
from inloop.normalize import normalize_html  # noqa: E402
from inloop.parser.markdown import render_markdown  # noqa: E402
from inloop.renderer.wechat import (  # noqa: E402
    available_themes,
    load_stylesheet,
    render_wechat_html,
    theme_name,
)

#: 对照页输出路径
OUTPUT = REPO_ROOT / "dist" / "theme-compare.html"

#: 预览画布宽度（模拟手机）
FRAME_WIDTH = 420

#: 示例正文。刻意把所有会被样式影响的元素都放进来：
#: 各级标题、段落、浅底卡片、深底卡片（嵌套引用）、列表、表格、代码、
#: 图片与图注、脚注、公式降级、行内强调。
SAMPLE = """# Light-O1：20Hz 人形基础模型到底意味着什么

> TL;DR：控制频率从 5Hz 提到 20Hz，带来的主要收益不是动作更精确，
> 而是闭环的可用带宽变宽了。

## Problem

用一个大模型直接输出人形机器人的关节指令，看起来是很自然的方向。
但落地时会碰到一个硬约束：**控制回路必须在有限时间内完成一次「感知 → 决策 → 执行」**。

### 计算预算

设控制周期为 $T$，则可用计算预算是：

```python
def budget(period: float, sense: float, actuate: float) -> float:
    \"\"\"留给策略推理的时间。\"\"\"
    return period - sense - actuate
```

> 引用外部评测时使用深底卡片：
>
> > 官方报告称该模型在动态平衡任务上的恢复时间缩短到 180ms，
> > 但**未公开**其扰动幅度的定义。
> >
> > 来源：某公开技术报告

## 对比

| 任务类型 | 对控制频率的敏感度 | 原因 |
|---|---|---|
| 慢速行走 | 低 | 动力学慢，误差可被后续修正 |
| 抓取静止物体 | 中 | 接触瞬间需要响应 |
| 动态平衡 | 高 | 扰动后必须在几十毫秒内响应 |

![架构示意](assets/architecture.png "图 1：分层架构示意")

## 判断

我的判断是：**20Hz 这类指标值得关注，但不要把它当成「更强的模型」来读。**

1. 两层的接口能不能学出来？
2. 频率与容量的置换曲线长什么样？

脚注引用[^1]，以及 ~~删除线~~ 与 `行内代码`。

[^1]: 这是脚注内容。

---

最后一段普通文字，用于观察段间距与行高。
"""


def main() -> int:
    config = load_config(REPO_ROOT)
    names = available_themes(config)
    if not names:
        print("styles/themes/ 下没有主题文件。")
        return 1

    # 当前生效的主题排最前，方便一眼确认默认观感
    current = theme_name(config)
    themes = tuple([current, *(n for n in names if n != current)]) if current in names else names

    body = normalize_html(render_markdown(SAMPLE).html).html
    frames: list[str] = []

    for theme in themes:
        sheet = load_stylesheet(config, theme)
        rendered = render_wechat_html(body, config=config, stylesheet=sheet).html
        frames.append(
            _frame(
                theme,
                rendered,
                warnings=rendered_warnings(rendered),
                current=(theme == current),
            )
        )
        print(f"  已渲染主题：{theme}" + ("（当前默认）" if theme == current else ""))

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(_document(frames, themes, current), encoding="utf-8", newline="\n")
    print(f"\n对照页已生成：{OUTPUT.relative_to(REPO_ROOT).as_posix()}")
    print("用浏览器打开即可并排对比；横向滚动查看更多主题。")
    return 0


def rendered_warnings(html: str) -> str:
    """给每个主题标注一行客观指标，便于在观感之外比较。"""
    import re

    text = re.sub(r"<[^>]+>", "", html)
    return f"正文纯字数 {len(text)}（越多说明排版越紧凑）"


def _frame(theme: str, inner_html: str, *, warnings: str, current: bool) -> str:
    """把一份渲染结果包成对照页里的一列。"""
    meta_style = "display:block;margin-top:4px;font-size:12px;color:#6b7280;"
    badge = (
        '<span style="margin-left:8px;padding:1px 8px;border-radius:10px;'
        'background:#002fa7;color:#fff;font-size:11px;">当前默认</span>'
        if current
        else ""
    )
    return (
        '<section style="flex:0 0 auto;margin:0 16px 0 0;">'
        f'<header style="{_header_style()}">'
        f'<strong style="font-size:15px;color:#002fa7;">{theme}</strong>{badge}'
        f'<span style="{meta_style}">{warnings}</span>'
        "</header>"
        f'<div style="{_canvas_style()}">{inner_html}</div>'
        "</section>"
    )


def _header_style() -> str:
    return (
        "margin:0 0 8px 0;padding:10px 14px;border-radius:8px;"
        "background:#eef2fb;font-family:-apple-system,BlinkMacSystemFont,'PingFang SC',sans-serif;"
    )


def _canvas_style() -> str:
    return (
        f"width:{FRAME_WIDTH}px;box-sizing:border-box;padding:20px 18px;"
        "background:#ffffff;border:1px solid #e5e7eb;border-radius:10px;"
        "box-shadow:0 1px 3px rgba(0,0,0,0.06);"
        "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
    )


def _document(frames: list[str], themes: tuple[str, ...], current: str) -> str:
    body_style = (
        "margin:0;padding:24px;background:#f0f0f3;"
        "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
    )
    row_style = "display:flex;align-items:flex-start;overflow-x:auto;padding-bottom:16px;"
    intro = (
        "<h1 style=\"margin:0 0 6px 0;font-size:20px;color:#22252b;\">"
        "排版主题对照</h1>"
        "<p style=\"margin:0 0 20px 0;font-size:14px;color:#6b7280;\">"
        f"共 {len(themes)} 个主题，当前默认为 <strong>{current}</strong>（排在最左）。"
        "同一段内容、同一套颜色，只有节奏与卡片形式不同。"
        "每个画布宽度 420px，接近手机阅读宽度。横向滚动可看全部。</p>"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        f"<title>排版主题对照</title>\n</head>\n"
        f'<body style="{body_style}">\n{intro}\n'
        f'<div style="{row_style}">\n{"".join(frames)}\n</div>\n'
        "</body>\n</html>\n"
    )


if __name__ == "__main__":
    sys.exit(main())
