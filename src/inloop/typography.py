"""发布排版覆盖：独立于 Markdown 和编辑器，所有构建入口共用。"""

from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any

FILE_NAME = "publishing-typography.json"
FONT_FAMILIES = {
    "system": "system-ui, -apple-system, BlinkMacSystemFont, sans-serif",
    "sans": '"PingFang SC", "Microsoft YaHei", Arial, sans-serif',
    "serif": '"Songti SC", SimSun, "Noto Serif CJK SC", serif',
}
FONT_LABELS = {"system": "系统默认", "sans": "无衬线", "serif": "衬线"}
LIMITS = {
    "font_size": (12, 24, 1, "正文字号（px）"),
    "heading_size": (16, 36, 1, "主标题字号（px）"),
    "line_height": (1.2, 2.5, 0.1, "行距倍数"),
    "paragraph_spacing": (0, 40, 1, "段间距（px）"),
}


class TypographyError(ValueError):
    """排版配置不合法或无法保存。"""


def validate_settings(values: object) -> dict[str, Any]:
    """校验局部覆盖；空字典表示继承，禁止任意 CSS 注入。"""
    if not isinstance(values, dict):
        raise TypographyError("发布排版必须是 JSON 对象；请使用设置面板重新保存。")
    for key, value in values.items():
        if key == "font_family":
            if not isinstance(value, str) or value not in FONT_FAMILIES:
                raise TypographyError("font_family 无效；请选择 system、sans 或 serif。")
        elif key in LIMITS:
            low, high, step, label = LIMITS[key]
            if (type(value) not in (int, float) or not math.isfinite(value)
                    or not low <= value <= high
                    or (step == 1 and value != int(value))):
                raise TypographyError(f"{key}（{label}）无效；请输入 {low}–{high} 范围内的数值。")
        else:
            raise TypographyError(f"未知发布排版字段 {key}；请移除此字段后重试。")
    return dict(values)


def _key(content_root: Path, article_id: int) -> str:
    root = os.path.normcase(str(content_root.resolve()))
    return f"{hashlib.sha256(root.encode('utf-8')).hexdigest()[:16]}:{article_id}"


def _load(root: Path) -> dict[str, Any]:
    path = root / "config" / FILE_NAME
    if not path.exists():
        return {"global": {}, "articles": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or set(data) != {"global", "articles"}:
            raise TypographyError("顶层必须包含 global 和 articles。")
        validate_settings(data["global"])
        if not isinstance(data["articles"], dict):
            raise TypographyError("articles 必须是对象。")
        for values in data["articles"].values():
            validate_settings(values)
        return data
    except (OSError, ValueError) as exc:
        raise TypographyError(f"发布排版配置读取失败：{path}：{exc}。请修正该文件后重试。") from exc


def read_typography(root: Path, content_root: Path, article_id: int) -> dict[str, Any]:
    """读取覆盖和表单约束；未覆盖的字段继续由主题决定。"""
    data = _load(root)
    article = data["articles"].get(_key(content_root, article_id), {})
    return {
        "global": data["global"], "article": article,
        "effective": {**data["global"], **article},
        "fonts": FONT_LABELS,
        "fields": {key: {"min": v[0], "max": v[1], "step": v[2], "label": v[3]}
                   for key, v in LIMITS.items()},
    }


def save_typography(
    root: Path, content_root: Path, article_id: int, values: object, *, global_scope: bool = False,
) -> dict[str, Any]:
    """替换指定范围的覆盖；先校验，再原子替换配置，不改内容源。"""
    checked = validate_settings(values)
    data = _load(root)
    if global_scope:
        data["global"] = checked
    elif checked:
        data["articles"][_key(content_root, article_id)] = checked
    else:
        data["articles"].pop(_key(content_root, article_id), None)
    path = root / "config" / FILE_NAME
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=".typography-", suffix=".tmp", delete=False,
        ) as stream:
            temporary = Path(stream.name)
            stream.write(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        temporary.replace(path)
    except OSError as exc:
        raise TypographyError(f"无法保存发布排版：{path}：{exc}。请检查目录写入权限。") from exc
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()
    return read_typography(root, content_root, article_id)
