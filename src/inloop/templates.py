"""模板系统：读取 ``templates/*.md`` 并填充占位符。

模板文件的结构：**文件开头的一行行 HTML 注释作为元数据，其余全文即为文章骨架**。
骨架里用 ``{{占位符}}`` 标记待填充处。

    <!-- name: paper-note -->
    <!-- description: 论文拆解 -->
    <!-- category: paper -->
    <!-- default_status: draft -->
    ---
    id: {{id}}
    ...
    ---

为什么元数据用注释而不是 YAML front matter：模板骨架本身就是一篇带 front matter
的文章。若元数据也用 ``---`` 包裹，渲染结果里会残留两个 front matter 块，
解析时第一个"赢了"，生成的文章就会拿到模板的元数据、真正的 front matter 变成正文。
用注释则完全不参与内容，渲染后自然消失，同时打开模板文件就能看到它的用途。

模板中**不写 ``id``**：文章编号由 :mod:`inloop.articles` 在创建时分配，
写死在模板里会让每篇新文章拿到同一个编号。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from inloop.models.article import Category, Status

#: 模板目录名（相对仓库根）
TEMPLATES_DIR = "templates"

#: 占位符语法：``{{name}}``
PLACEHOLDER_START = "{{"
PLACEHOLDER_END = "}}"

#: 元数据注释：``<!-- key: value -->``
_META_PATTERN = re.compile(
    r"^\s*<!--\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*:\s*(?P<value>.*?)\s*-->\s*$"
)

#: 模板元数据中必须提供的键
REQUIRED_META: tuple[str, ...] = ("name", "description", "category", "default_status")


class TemplateError(ValueError):
    """模板读取或渲染失败。"""


@dataclass(frozen=True, slots=True)
class Template:
    """一个文章模板。

    Attributes:
        name: 模板名，即文件名去掉 ``.md``，也是 ``--template`` 的取值。
        description: 模板用途说明，用于 ``inloop new --list`` 展示。
        category: 该模板默认对应的栏目。
        default_status: 新建文章时的初始状态。
        skeleton: 文章骨架全文（含 front matter 与正文，占位符未填充）。
        path: 模板文件路径。
    """

    name: str
    description: str
    category: Category
    default_status: Status
    skeleton: str
    path: Path


def templates_dir(root: Path) -> Path:
    """返回仓库内的模板目录。"""
    return root / TEMPLATES_DIR


def available_templates(root: Path) -> tuple[str, ...]:
    """列出可用模板名，按字母序。

    只认目录下的 ``*.md``；``README.md`` 是目录说明，不当作模板。
    """
    directory = templates_dir(root)
    if not directory.is_dir():
        return ()
    return tuple(
        sorted(path.stem for path in directory.glob("*.md") if path.stem.lower() != "readme")
    )


def load_template(root: Path, name: str) -> Template:
    """读取指定模板。

    Raises:
        TemplateError: 模板不存在、缺少元数据，或元数据取值非法。
    """
    path = templates_dir(root) / f"{name}.md"
    if not path.is_file():
        available = available_templates(root)
        hint = "、".join(available) if available else "（目录内没有可用模板）"
        raise TemplateError(
            f"找不到模板 `{name}`：{path} 不存在。\n"
            f"可用模板：{hint}。\n"
            f"修正方法：改用上述之一，或在 {TEMPLATES_DIR}/ 下新建 `{name}.md`。"
        )

    text = path.read_text(encoding="utf-8")
    meta, skeleton = parse_template_meta(text)

    for key in REQUIRED_META:
        if key not in meta:
            raise TemplateError(
                f"模板 {path} 缺少元数据 `{key}`。\n"
                f"修正方法：在文件开头加一行 `<!-- {key}: 取值 -->`，"
                f"必需的元数据为：{', '.join(REQUIRED_META)}。"
            )

    declared_name = meta["name"]
    if declared_name != name:
        raise TemplateError(
            f"模板 {path} 的元数据 name 为 `{declared_name}`，与文件名 `{name}` 不一致。\n"
            f"修正方法：把 `<!-- name: ... -->` 改成 `{name}`，或重命名文件。"
        )

    category = _parse_category(meta["category"], path)
    default_status = _parse_status(meta["default_status"], path)

    if re.search(r"^\s*id\s*:", skeleton, flags=re.MULTILINE) and "{{id}}" not in skeleton:
        raise TemplateError(
            f"模板 {path} 的骨架里出现了写死的 `id` 字段：文章编号在创建时自动分配，"
            f"写死会让每篇新文章拿到同一个编号。\n"
            f"修正方法：把 `id:` 的值改为占位符 `{{{{id}}}}`。"
        )

    return Template(
        name=name,
        description=meta["description"],
        category=category,
        default_status=default_status,
        skeleton=skeleton,
        path=path,
    )


def parse_template_meta(text: str) -> tuple[dict[str, str], str]:
    """分离模板开头的元数据注释与文章骨架。

    Returns:
        ``(元数据字典, 骨架文本)``。骨架已去掉开头的空行。
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    meta: dict[str, str] = {}
    consumed = 0

    for index, line in enumerate(lines):
        # 允许元数据之间夹杂空行
        if line.strip() == "":
            consumed = index + 1
            continue
        match = _META_PATTERN.match(line)
        if match is None:
            break
        meta[match.group("key")] = match.group("value").strip()
        consumed = index + 1

    skeleton = "\n".join(lines[consumed:]).lstrip("\n")
    return meta, skeleton


def render_template_text(template: Template, values: dict[str, str]) -> str:
    """用给定取值填充模板骨架。

    骨架里此刻还是 ``{{占位符}}``，未必能通过文章模型校验，
    因此这里按普通文本处理，而不是先构造模型。
    """
    return substitute(template.skeleton, values)


def substitute(text: str, values: dict[str, str]) -> str:
    """把文本中的 ``{{name}}`` 替换为给定取值。"""
    result = text
    for key, value in values.items():
        result = result.replace(f"{PLACEHOLDER_START}{key}{PLACEHOLDER_END}", value)
    return result


def find_placeholders(text: str) -> tuple[str, ...]:
    """找出文本中剩余的全部占位符名，用于排查「模板漏填」。"""
    found: list[str] = []
    cursor = 0
    while True:
        start = text.find(PLACEHOLDER_START, cursor)
        if start == -1:
            break
        end = text.find(PLACEHOLDER_END, start + len(PLACEHOLDER_START))
        if end == -1:
            break
        name = text[start + len(PLACEHOLDER_START) : end].strip()
        if name and name not in found:
            found.append(name)
        cursor = end + len(PLACEHOLDER_END)
    return tuple(found)


def _parse_category(value: str, path: Path) -> Category:
    try:
        return Category(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Category)
        raise TemplateError(
            f"模板 {path} 的 category 取值不合法：`{value}`。"
            f"允许的取值为：{allowed}（任务书 §16）。"
        ) from exc


def _parse_status(value: str, path: Path) -> Status:
    try:
        return Status(value)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in Status)
        raise TemplateError(
            f"模板 {path} 的 default_status 取值不合法：`{value}`。"
            f"允许的取值为：{allowed}（任务书 §4）。"
        ) from exc
