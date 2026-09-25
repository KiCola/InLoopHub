"""Front Matter 解析：Markdown 文本 → ``(meta, body)``。

职责边界（AGENTS.md §7、docs/architecture.md 第 2 节）：

- **负责**：切出 YAML 块、解析 YAML、返回正文。纯函数，无副作用。
- **不负责**：判断字段合不合法。「``date`` 格式对不对」「``status`` 是否在枚举内」
  属于模型与校验层的职责，见 :mod:`inloop.models.article`。

把这两件事分开的原因：解析失败与内容不合格是两类问题，报错方式、退出码、
给用户的修复建议都不同。混在一起会导致「格式合法但字段缺失」只能报一句笼统的错。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import yaml

#: Front Matter 定界符（任务书 §4 要求文章以 ``---`` 包裹 YAML）
DELIMITER = "---"

#: UTF-8 BOM。Windows 编辑器可能写入，必须在解析前剥掉，否则第一行不等于 ``---``。
_BOM = "\ufeff"


class _FrontMatterLoader(yaml.SafeLoader):
    """不把日期解析成 date 的 YAML 加载器。

    默认的 YAML 解析器会把 `date: 2026-09-25` 直接构造成 ``datetime.date``，
    遇到 `2026-02-30` 这种不存在的日期会在**解析阶段**抛出底层错误
    （``day is out of range for month``），而加引号写同样的值却会走到校验阶段。
    同一个错误出现两种报错方式，是无法接受的。

    这里去掉时间戳的隐式解析，使日期始终以字符串进入模型层，
    由 :mod:`inloop.models.article` 统一校验与报错。
    """


# 浅拷贝一份解析器表，删除时间戳规则；不影响全局 SafeLoader。
_FrontMatterLoader.yaml_implicit_resolvers = {
    key: [rule for rule in rules if rule[0] != "tag:yaml.org,2002:timestamp"]
    for key, rules in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


class FrontMatterError(ValueError):
    """Front Matter 结构或语法有误。

    错误信息必须说明「哪里错了 + 为什么 + 怎么改」，见 AGENTS.md §4。
    """


@dataclass(frozen=True, slots=True)
class FrontMatter:
    """一次解析的结果。

    Attributes:
        meta: YAML 解析出的元数据映射。
        body: Front Matter 之后的正文，原样保留（未做任何裁剪或规范化）。
        body_offset: 正文第一行在原始文本中的行号（1 起）。
            用于把模型层的校验结果定位回源文件，是「报错要能指到行」的前提。
    """

    meta: dict[str, Any]
    body: str
    body_offset: int


#: 使用的 YAML 加载器：继承 SafeLoader 并关闭时间戳隐式解析，
#: 既不允许构造任意 Python 对象，也让日期统一以字符串进入校验层。
FrontMatterLoader = _FrontMatterLoader


def parse_front_matter(text: str) -> FrontMatter:
    """从 Markdown 文本中解析出 Front Matter 与正文。

    Args:
        text: 文章全文。允许带 UTF-8 BOM，允许 CRLF 换行。

    Returns:
        解析结果。``meta`` 为 YAML 映射，``body`` 为正文。

    Raises:
        FrontMatterError: 缺少定界符、YAML 语法错误、顶层不是映射，或块内为空。
    """
    if text.startswith(_BOM):
        text = text[len(_BOM) :]

    lines = text.split("\n")

    # 允许文件以空行开头（有些编辑器会留），但不允许在定界符之前出现实际内容。
    first_index = 0
    while first_index < len(lines) and lines[first_index].strip() == "":
        first_index += 1

    if first_index >= len(lines):
        raise FrontMatterError(
            "文件内容为空，未找到 Front Matter。\n"
            "修正方法：按任务书 §4，在文件开头写入 `---` 包裹的 YAML 元数据块。"
        )

    if lines[first_index].strip() != DELIMITER:
        raise FrontMatterError(
            f"第 {first_index + 1} 行不是 Front Matter 起始定界符 `{DELIMITER}`，"
            f"实际为 {_preview(lines[first_index])}。\n"
            "修正方法：把元数据块移到文件最开头，并用单独一行的 `---` 包裹：\n"
            "    ---\n"
            "    id: 001\n"
            "    title: \"标题\"\n"
            "    ---\n"
            "注意定界符必须是该行的全部内容（前后除了空格不能有别的字符）。"
        )

    # 找到结束定界符
    end_index: int | None = None
    for index in range(first_index + 1, len(lines)):
        if lines[index].strip() == DELIMITER:
            end_index = index
            break

    if end_index is None:
        raise FrontMatterError(
            f"第 {first_index + 1} 行开始了 Front Matter，但直到文件末尾都没有找到"
            f"结束定界符 `{DELIMITER}`。\n"
            "修正方法：在元数据块结束后补一行只含 `---` 的定界符。"
        )

    yaml_source = "\n".join(lines[first_index + 1 : end_index])
    if yaml_source.strip() == "":
        raise FrontMatterError(
            f"Front Matter 块为空：第 {first_index + 1} 行的 `{DELIMITER}` 之后"
            f"紧接着第 {end_index + 1} 行的 `{DELIMITER}`，中间没有任何字段。\n"
            "修正方法：按任务书 §4 补齐必需字段，例如 id、title、slug、date、"
            "author、category、status、tags、summary、cover、platforms。"
        )

    try:
        # 使用关闭了时间戳解析的 SafeLoader 子类；禁止任何可构造任意对象的加载器。
        loaded = yaml.load(yaml_source, Loader=FrontMatterLoader)
    except yaml.YAMLError as exc:
        raise FrontMatterError(
            f"Front Matter 不是合法 YAML（第 {first_index + 2} 行起）。\n"
            f"原始错误：{exc}\n"
            "常见原因与修正：\n"
            "  - 使用了 Tab 缩进：YAML 只允许空格，改成空格缩进；\n"
            "  - 冒号后缺空格：`title:标题` 应写成 `title: 标题`；\n"
            "  - 含冒号或 # 的字符串没加引号：改为 `title: \"含: 冒号 的标题\"`；\n"
            "  - 列表项缩进不一致。"
        ) from exc
    except ValueError as exc:
        # 兜底：某些取值在构造阶段仍可能抛 ValueError。不能让它以程序崩溃的形式暴露。
        raise FrontMatterError(
            f"Front Matter 中有无法解析的取值（第 {first_index + 2} 行起）：{exc}。\n"
            "修正方法：检查数字与日期写法，或给该字段加引号使其保持文本。"
        ) from exc

    if loaded is None:
        raise FrontMatterError(
            "Front Matter 解析结果为空。\n"
            "修正方法：检查元数据块是否只有注释行，或缩进导致所有字段都成了上一项的从属内容。"
        )

    if not isinstance(loaded, dict):
        raise FrontMatterError(
            f"Front Matter 顶层必须是映射（键值对），实际解析为 {type(loaded).__name__}。\n"
            f"实际内容：{_preview(str(loaded))}\n"
            "修正方法：确认为形如 `id: 001`、`title: \"标题\"` 的键值结构，"
            "而不是列表或纯标量。"
        )

    body = "\n".join(lines[end_index + 1 :])

    return FrontMatter(meta=loaded, body=body, body_offset=end_index + 2)


def _preview(value: str, limit: int = 40) -> str:
    """生成一行内容预览，用于错误信息里指明「实际是什么」。"""
    text = value.strip()
    if not text:
        return "空行"
    if len(text) > limit:
        return f"`{text[:limit]}…`"
    return f"`{text}`"
