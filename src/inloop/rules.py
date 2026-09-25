"""校验规则码的集中表。

为什么要有这张表：

- 规则码是**对外契约**（CI 依据它决定是否 fail，文档引用它，测试固定它的行为）。
  散落在各校验分支里的字符串字面量无法被遍历、无法被校验、改一处很难找全。
- ``check`` 命令与本模块共用同一份定义，避免"文档写了一个码、代码里没有"。
- 测试可以断言：所有报出的问题码都在这张表里，且级别与表一致。

新增规则时同时更新本表与任务书中对应的检查项清单。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class IssueLevel(StrEnum):
    """问题级别。

    - ``ERROR``：必须修，否则构建中止、退出码非 0。
    - ``WARNING``：可以继续，但必须打印出来让人看到。
    """

    ERROR = "ERROR"
    WARNING = "WARNING"


class RuleGroup(StrEnum):
    """规则码前缀，按检查对象分组。"""

    FRONT_MATTER = "FM"
    IMAGE = "IMG"
    MARKDOWN = "MD"


@dataclass(frozen=True, slots=True)
class Rule:
    """一条校验规则。

    Attributes:
        code: 规则码，形如 ``FM001``。稳定不变，是对外契约。
        level: 问题级别。
        summary: 规则说明，用于文档与 `check --rules` 之类的展示。
    """

    code: str
    level: IssueLevel
    summary: str


# --- Front Matter（任务书 §4）--------------------------------------------

FM_MISSING_FIELD = Rule("FM001", IssueLevel.ERROR, "缺少任务书 §4 规定的必需字段")
FM_INVALID_SLUG = Rule("FM002", IssueLevel.ERROR, "slug 不符合小写连字符格式")
FM_EMPTY_TAGS = Rule("FM003", IssueLevel.WARNING, "tags 为空")
FM_EMPTY_SUMMARY = Rule("FM004", IssueLevel.WARNING, "summary 为空")
FM_SUMMARY_TOO_LONG = Rule("FM005", IssueLevel.WARNING, "summary 超过 120 字")
FM_FUTURE_DATE = Rule("FM006", IssueLevel.WARNING, "date 晚于今天")
FM_NO_TITLE_HEADING = Rule("FM007", IssueLevel.WARNING, "正文中没有一级标题")
FM_INVALID_ID = Rule("FM008", IssueLevel.ERROR, "id 不是整数")
FM_FIELD_NOT_STRING = Rule("FM009", IssueLevel.ERROR, "字段应为字符串但被解析成其他类型")
FM_EMPTY_TITLE = Rule("FM010", IssueLevel.ERROR, "title 为空")
FM_INVALID_DATE = Rule("FM011", IssueLevel.ERROR, "date 格式非法或不是真实存在的日期")
FM_INVALID_CATEGORY = Rule("FM012", IssueLevel.ERROR, "category 不在任务书 §16 的枚举内")
FM_INVALID_STATUS = Rule("FM013", IssueLevel.ERROR, "status 不在任务书 §4 的枚举内")
FM_TAGS_NOT_LIST = Rule("FM014", IssueLevel.ERROR, "tags 不是列表")
FM_PLATFORMS_NOT_MAPPING = Rule("FM015", IssueLevel.ERROR, "platforms 不是映射")
FM_WECHAT_DISABLED = Rule("FM016", IssueLevel.ERROR, "platforms.wechat 未开启")
FM_DIR_NAME_FORMAT = Rule("FM017", IssueLevel.WARNING, "文章目录名不符合 序号-slug 约定")
FM_DIR_ID_MISMATCH = Rule("FM018", IssueLevel.WARNING, "目录名序号与 front matter 的 id 不一致")
FM_TAG_NOT_STRING = Rule("FM019", IssueLevel.WARNING, "tags 中含非字符串项，已忽略")
FM_TAG_NOT_BOOL = Rule("FM020", IssueLevel.WARNING, "platforms 的值不是布尔类型")

# --- 图片（任务书 §11）---------------------------------------------------

IMG_MISSING = Rule("IMG001", IssueLevel.ERROR, "正文引用的本地图片不存在")
IMG_ABSOLUTE_PATH = Rule("IMG002", IssueLevel.ERROR, "图片使用了绝对路径或盘符路径")
IMG_COVER_MISSING = Rule("IMG003", IssueLevel.ERROR, "cover 指向的文件不存在")
IMG_UNSUPPORTED_FORMAT = Rule("IMG004", IssueLevel.ERROR, "图片格式不受支持")
IMG_TOO_LARGE_ERROR = Rule("IMG005", IssueLevel.ERROR, "图片超过体积上限")
IMG_MISSING_ALT = Rule("IMG101", IssueLevel.WARNING, "正文图片缺少有意义的 alt")
IMG_TOO_LARGE_WARNING = Rule("IMG102", IssueLevel.WARNING, "图片体积偏大")
IMG_MISSING_CAPTION = Rule("IMG103", IssueLevel.WARNING, "图片缺少 title（caption）")
IMG_EXTERNAL = Rule(
    "IMG104",
    IssueLevel.WARNING,
    "正文引用了外链图片，微信编辑器不会抓取，粘贴后图片会丢失",
)
EMBED_NOT_FOUND = Rule(
    "IMG105",
    IssueLevel.ERROR,
    "Obsidian 嵌入语法（![[文件名]]）指向的图片找不到",
)

# --- Markdown（任务书 §5）------------------------------------------------

MD_PARSE_FAILED = Rule("MD001", IssueLevel.ERROR, "Markdown 解析失败或产出非法 HTML")
MD_RAW_FOOTNOTE = Rule("MD101", IssueLevel.WARNING, "脚注在微信端无法跳转，已降级")
MD_TABLE_RAGGED = Rule("MD102", IssueLevel.WARNING, "表格列数不一致")
MD_MATH_UNSUPPORTED = Rule("MD103", IssueLevel.WARNING, "公式在微信端无法渲染，已降级为文本")
MD_TASK_CHECKBOX = Rule("MD104", IssueLevel.WARNING, "任务列表复选框在微信端不可用，已降级为文本")
MD_FORBIDDEN_TAG = Rule("MD105", IssueLevel.WARNING, "产物中不允许出现的标签已被移除")


#: 全部规则，按规则码排序，便于展示与比对。
ALL_RULES: tuple[Rule, ...] = tuple(
    sorted(
        (
            FM_MISSING_FIELD,
            FM_INVALID_SLUG,
            FM_EMPTY_TAGS,
            FM_EMPTY_SUMMARY,
            FM_SUMMARY_TOO_LONG,
            FM_FUTURE_DATE,
            FM_NO_TITLE_HEADING,
            FM_INVALID_ID,
            FM_FIELD_NOT_STRING,
            FM_EMPTY_TITLE,
            FM_INVALID_DATE,
            FM_INVALID_CATEGORY,
            FM_INVALID_STATUS,
            FM_TAGS_NOT_LIST,
            FM_PLATFORMS_NOT_MAPPING,
            FM_WECHAT_DISABLED,
            FM_DIR_NAME_FORMAT,
            FM_DIR_ID_MISMATCH,
            FM_TAG_NOT_STRING,
            FM_TAG_NOT_BOOL,
            IMG_MISSING,
            IMG_ABSOLUTE_PATH,
            IMG_COVER_MISSING,
            IMG_UNSUPPORTED_FORMAT,
            IMG_TOO_LARGE_ERROR,
            IMG_MISSING_ALT,
            IMG_TOO_LARGE_WARNING,
            IMG_MISSING_CAPTION,
            IMG_EXTERNAL,
            MD_PARSE_FAILED,
            MD_RAW_FOOTNOTE,
            MD_TABLE_RAGGED,
            MD_MATH_UNSUPPORTED,
            MD_TASK_CHECKBOX,
            MD_FORBIDDEN_TAG,
        ),
        key=lambda rule: rule.code,
    )
)

#: 规则码 → 规则，便于按码查询与一致性校验。
RULES_BY_CODE: dict[str, Rule] = {rule.code: rule for rule in ALL_RULES}


def get_rule(code: str) -> Rule:
    """按规则码取规则。

    Raises:
        KeyError: 规则码不在表中。这种失败必须暴露，不能静默降级——
            否则会出现"报了错但没人知道这码是什么意思"。
    """
    try:
        return RULES_BY_CODE[code]
    except KeyError as exc:
        raise KeyError(
            f"未知规则码 `{code}`。请先在 src/inloop/rules.py 的规则表中登记，"
            f"再在各校验分支引用对应的常量。"
        ) from exc
