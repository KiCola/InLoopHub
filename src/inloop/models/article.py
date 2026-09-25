"""文章数据模型。

职责边界（AGENTS.md §7、docs/architecture.md 第 1 节）：

- **负责**：front matter 的语义——字段取值约束、``slug`` 格式、状态合法性、
  以及把这些判断收集成可逐条展示的问题清单。
- **不负责**：读文件、解析 YAML、渲染 HTML。

校验刻意**收集**问题而不是遇到第一个就抛异常：一次运行把所有问题报全，
比让人反复改一轮跑一轮有用（任务书 §7.2 要求输出 PASS / WARNING / ERROR 三级结果）。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from pathlib import Path
from typing import Any

from inloop.parser.frontmatter import FrontMatter, FrontMatterError, parse_front_matter
from inloop.rules import (
    FM_DIR_ID_MISMATCH,
    FM_DIR_NAME_FORMAT,
    FM_EMPTY_SUMMARY,
    FM_EMPTY_TAGS,
    FM_EMPTY_TITLE,
    FM_FIELD_NOT_STRING,
    FM_FUTURE_DATE,
    FM_INVALID_CATEGORY,
    FM_INVALID_DATE,
    FM_INVALID_ID,
    FM_INVALID_SLUG,
    FM_INVALID_STATUS,
    FM_MISSING_FIELD,
    FM_NO_TITLE_HEADING,
    FM_PLATFORMS_NOT_MAPPING,
    FM_SUMMARY_TOO_LONG,
    FM_TAG_NOT_BOOL,
    FM_TAG_NOT_STRING,
    FM_TAGS_NOT_LIST,
    FM_WECHAT_DISABLED,
    IssueLevel,
    Rule,
    get_rule,
)


class Status(StrEnum):
    """文章所处阶段（任务书 §4、§17）。"""

    IDEA = "idea"
    RESEARCHING = "researching"
    DRAFT = "draft"
    REVIEW = "review"
    READY = "ready"
    PUBLISHED = "published"


class Category(StrEnum):
    """公众号内容栏目（任务书 §16）。"""

    PAPER = "paper"
    CODE = "code"
    BUILD = "build"
    RESEARCH = "research"
    DIARY = "diary"

    @property
    def label(self) -> str:
        """栏目中文名，用于 CLI 展示。"""
        return _CATEGORY_LABELS[self]


_CATEGORY_LABELS: dict[Category, str] = {
    Category.PAPER: "论文拆解",
    Category.CODE: "源码深挖",
    Category.BUILD: "实验日志",
    Category.RESEARCH: "研究随想",
    Category.DIARY: "科研生活",
}

#: 任务书 §4 规定必须存在的字段
REQUIRED_FIELDS: tuple[str, ...] = (
    "id",
    "title",
    "slug",
    "date",
    "author",
    "category",
    "status",
    "tags",
    "summary",
    "cover",
    "platforms",
)

#: slug 允许的形式：小写字母数字，用连字符连接
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

#: 目录名形如 ``001-hello-inloop``
ARTICLE_DIR_PATTERN = re.compile(r"^(?P<number>\d{3})-(?P<slug>.+)$")


@dataclass(frozen=True, slots=True)
class Issue:
    """一条校验问题。

    ``rule`` 持有规则表里的规则对象而不是裸字符串：级别、说明都只有一处定义，
    "报出的级别与规则表不一致"因此在类型层面不可能发生。

    Attributes:
        rule: 命中的规则，来自 :mod:`inloop.rules`。
        message: 人话说明，包含「哪里错了 + 为什么 + 怎么改」。
        field: 涉及的 front matter 字段名；与字段无关时为 None。
        line: 源文件行号（1 起）；无法定位时为 None。
    """

    rule: Rule
    message: str
    field: str | None = None
    line: int | None = None

    @property
    def code(self) -> str:
        """规则码，转发自规则表。"""
        return self.rule.code

    @property
    def level(self) -> IssueLevel:
        """问题级别，转发自规则表。"""
        return self.rule.level

    def render(self, path: Path | None = None) -> str:
        """格式化为一行可读文本，形如 ``文件:行号 规则码 [级别] 说明``。"""
        location = str(path) if path else "<内存>"
        if self.line is not None:
            location = f"{location}:{self.line}"
        return f"{location} {self.code} [{self.level.value}] {self.message}"


class ArticleError(ValueError):
    """文章无法构建为模型（结构性错误，而非内容警告）。"""


@dataclass(frozen=True, slots=True)
class Article:
    """一篇手记文章。

    Attributes:
        id: 文章编号，全仓库唯一递增，用于稳定排序。
        title: 标题。
        slug: 英文短名，用于文件名与产物目录名。
        date: 写作日期。
        author: 作者。
        category: 栏目。
        status: 阶段。
        tags: 标签，至少一个。
        summary: 摘要。
        cover: 封面图，相对文章目录的路径。
        platforms: 平台开关，至少 ``wechat`` 为 True。
        body: 正文 Markdown（不含 front matter）。
        extra: front matter 中未被模型识别的字段，原样保留，不丢弃。
        issues: 校验过程中收集到的问题。
        source: 源文件路径；由内存构造时为 None。
    """

    id: int
    title: str
    slug: str
    date: date
    author: str
    category: Category
    status: Status
    tags: tuple[str, ...]
    summary: str
    cover: str
    platforms: dict[str, bool]
    body: str
    extra: dict[str, Any] = field(default_factory=dict)
    issues: tuple[Issue, ...] = ()
    source: Path | None = None

    @property
    def is_valid(self) -> bool:
        """是否没有 ERROR 级问题。"""
        return not any(issue.level is IssueLevel.ERROR for issue in self.issues)

    @property
    def errors(self) -> tuple[Issue, ...]:
        """全部 ERROR 级问题。"""
        return tuple(i for i in self.issues if i.level is IssueLevel.ERROR)

    @property
    def warnings(self) -> tuple[Issue, ...]:
        """全部 WARNING 级问题。"""
        return tuple(i for i in self.issues if i.level is IssueLevel.WARNING)

    @property
    def directory_name(self) -> str:
        """文章目录名，形如 ``002-light-o1``（任务书 §3）。"""
        return f"{self.id:03d}-{self.slug}"

    def to_markdown(self, body: str | None = None) -> str:
        """渲染为完整的 Markdown 文本（front matter + 正文）。

        实现在 :mod:`inloop.models.serializer`；这里只做转发，避免调用方
        为了「把文章写回文本」而多 import 一个模块。
        """
        from inloop.models.serializer import render_article_text

        return render_article_text(self, body=body)

    def publishes_to(self, platform: str) -> bool:
        """判断文章是否要发布到某个平台。"""
        return bool(self.platforms.get(platform, False))

    # --- 构造 -------------------------------------------------------------

    @classmethod
    def from_text(cls, text: str, source: Path | None = None) -> Article:
        """从文章全文构造模型。

        Args:
            text: 含 front matter 的文章全文。
            source: 源文件路径，仅用于报错定位，不读该文件。

        Returns:
            构造好的 :class:`Article`，可能带 ``issues``。

        Raises:
            ArticleError: front matter 结构性错误，无法继续（由
                :class:`~inloop.parser.frontmatter.FrontMatterError` 转换而来）。
        """
        try:
            front = parse_front_matter(text)
        except FrontMatterError as exc:
            raise ArticleError(str(exc)) from exc
        return cls.from_front_matter(front, source=source)

    @classmethod
    def from_front_matter(cls, front: FrontMatter, source: Path | None = None) -> Article:
        """从已解析的 front matter 构造模型。

        结构性问题（必需字段缺失、取值非法）会记录为 ERROR 问题而不是抛异常，
        使调用方能够一次列出全部问题。
        """
        meta = front.meta
        issues: list[Issue] = []

        # 1) 必需字段是否齐全
        missing = [name for name in REQUIRED_FIELDS if name not in meta]
        for name in missing:
            issues.append(
                Issue(
                    rule=FM_MISSING_FIELD,
                    field=name,
                    line=1,
                    message=(
                        f"缺少必需字段 `{name}`。"
                        f"修正方法：在 front matter 中补上 `{name}:`，字段清单见任务书 §4。"
                    ),
                )
            )

        # 2) 逐字段取值解析，失败时用占位值继续，保证其余问题也能被一起报出来
        article_id, id_ok = _parse_id(meta.get("id"), issues)
        title = _parse_str(meta.get("title"), "title", issues)
        slug = _parse_str(meta.get("slug"), "slug", issues)
        parsed_date = _parse_date(meta.get("date"), issues)
        author = _parse_str(meta.get("author"), "author", issues)
        category = _parse_category(meta.get("category"), issues)
        status = _parse_status(meta.get("status"), issues)
        tags = _parse_tags(meta.get("tags"), issues)
        summary = _parse_str(meta.get("summary"), "summary", issues)
        cover = _parse_str(meta.get("cover"), "cover", issues)
        platforms = _parse_platforms(meta.get("platforms"), issues)

        # 3) slug 格式
        if slug and not SLUG_PATTERN.match(slug):
            issues.append(
                Issue(
                    rule=FM_INVALID_SLUG,
                    field="slug",
                    message=(
                        f"slug 格式不合法：`{slug}`。"
                        "只允许小写字母、数字与连字符，且不能以连字符开头或结尾，"
                        "例如 `light-o1`。修正方法：改为全小写并用连字符分词。"
                    ),
                )
            )

        # 4) 目录名与 id 是否一致（需要源路径才能判断；id 本身报错时跳过）
        if id_ok:
            directory_issue = _check_directory_name(source, article_id)
            if directory_issue is not None:
                issues.append(directory_issue)

        # 5) tags 为空
        if not tags:
            issues.append(
                Issue(
                    rule=FM_EMPTY_TAGS,
                    field="tags",
                    line=1,
                    message=(
                        "tags 为空。修正方法：补上至少一个标签，"
                        "标签是后续做内容索引与检索的主要依据。"
                    ),
                )
            )

        # 6) summary 为空或过长（长度按码点计，见 AGENTS.md §6）
        if not summary:
            issues.append(
                Issue(
                    rule=FM_EMPTY_SUMMARY,
                    field="summary",
                    line=1,
                    message="summary 为空。修正方法：补上一句话摘要，发布时要用。",
                )
            )
        elif len(summary) > 120:
            issues.append(
                Issue(
                    rule=FM_SUMMARY_TOO_LONG,
                    field="summary",
                    message=(
                        f"summary 过长（{len(summary)} 字，建议不超过 120 字）。"
                        "修正方法：压缩到一句话，写清「解决什么问题、结论是什么」。"
                    ),
                )
            )

        # 7) 未来日期
        today = date.today()
        if parsed_date > today:
            issues.append(
                Issue(
                    rule=FM_FUTURE_DATE,
                    field="date",
                    message=(
                        f"date 晚于今天（{parsed_date.isoformat()} > {today.isoformat()}）。"
                        "修正方法：确认是否写错年份；若确实计划未来发布，可保留。"
                    ),
                )
            )

        # 8) 正文没有一级标题
        if not any(line.startswith("# ") for line in front.body.splitlines()):
            issues.append(
                Issue(
                    rule=FM_NO_TITLE_HEADING,
                    line=front.body_offset,
                    message=(
                        "正文中没有一级标题（`# 标题`）。"
                        "修正方法：按任务书 §6 的模板结构补上正文大标题。"
                    ),
                )
            )

        known = set(REQUIRED_FIELDS)
        extra = {key: value for key, value in meta.items() if key not in known}

        # 一致性自检：报出的规则码必须存在于规则表中。
        # 放在这里而不是只在测试里，是因为"报了一个没人认识的错误码"属于程序缺陷，
        # 必须立刻暴露，不能让用户拿着一个查不到的码去搜索。
        for issue in issues:
            get_rule(issue.code)

        return cls(
            id=article_id,
            title=title,
            slug=slug,
            date=parsed_date,
            author=author,
            category=category,
            status=status,
            tags=tags,
            summary=summary,
            cover=cover,
            platforms=platforms,
            body=front.body,
            extra=extra,
            issues=tuple(issues),
            source=source,
        )


# --- 字段解析辅助 ---------------------------------------------------------
# 这些函数不抛异常，而是把问题追加到 issues 并返回一个安全的占位值，
# 使「一个字段写错」不会掩盖「另一个字段也写错」。

_DEFAULT_ID = 0
_DEFAULT_DATE = date(1970, 1, 1)
_DEFAULT_CATEGORY = Category.DIARY
_DEFAULT_STATUS = Status.DRAFT


def _parse_id(value: Any, issues: list[Issue]) -> tuple[int, bool]:
    """解析 ``id``。

    Returns:
        ``(id, 是否解析成功)``。失败时返回占位值并记录问题，由调用方决定
        是否跳过依赖 id 的其他校验（例如目录名比对）。
    """
    if value is None:
        return _DEFAULT_ID, False
    try:
        return int(str(value).strip()), True
    except (TypeError, ValueError):
        issues.append(
            Issue(
                rule=FM_INVALID_ID,
                field="id",
                message=(
                    f"id 必须是整数，实际为 `{value}`。"
                    "修正方法：改为数字，例如 `id: 2`（目录名中的 `002` 是补零后的展示形式）。"
                ),
            )
        )
        return _DEFAULT_ID, False


def _parse_str(value: Any, name: str, issues: list[Issue]) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value.strip()
    elif isinstance(value, (int, float, bool)):
        # 例如 title 写成纯数字，YAML 会解析成 int；不要静默接受，提示加引号
        text = str(value)
        issues.append(
            Issue(
                rule=FM_FIELD_NOT_STRING,
                field=name,
                message=(
                    f"`{name}` 应为字符串，YAML 把它解析成了 {type(value).__name__}（`{value}`）。"
                    f'修正方法：加引号，例如 `{name}: "{value}"`。'
                ),
            )
        )
    else:
        text = ""
        issues.append(
            Issue(
                rule=FM_FIELD_NOT_STRING,
                field=name,
                message=(
                    f"`{name}` 应为字符串，实际为 {type(value).__name__}。"
                    f"修正方法：改写为一行文本。"
                ),
            )
        )

    if name == "title" and not text:
        issues.append(
            Issue(
                    rule=FM_EMPTY_TITLE,
                field="title",
                message="title 不能为空。修正方法：补上文章标题。",
                )
        )
    return text


def _parse_date(value: Any, issues: list[Issue]) -> date:
    if value is None:
        return _DEFAULT_DATE

    # PyYAML 在不同写法下会给出不同类型：
    #   date: 2026-09-25        → datetime.date（已可用）
    #   date: "2026-09-25"      → str，但内容合法
    #   date: 2026-9-25         → str，需规范化
    #   date: 2026/09/25        → str，非法
    # 策略：字符串只要内容符合 YYYY-MM-DD 就规范化，否则报错。
    if isinstance(value, date):
        return value

    text = str(value).strip()
    parts = text.split("-")
    if len(parts) == 3 and all(part.isdigit() for part in parts):
        year, month, day = (int(part) for part in parts)
        try:
            return date(year, month, day)
        except ValueError as exc:
            issues.append(
                Issue(
                    rule=FM_INVALID_DATE,
                    field="date",
                    message=(
                        f"date 不是真实存在的日期：`{text}`（{exc}）。"
                        "修正方法：改成存在的日期，例如 `date: 2026-09-25`。"
                    ),
                )
            )
            return _DEFAULT_DATE

    issues.append(
        Issue(
            rule=FM_INVALID_DATE,
            field="date",
            message=(
                f"date 格式不合法：`{text}`。要求 `YYYY-MM-DD`。"
                "修正方法：写成 `date: 2026-09-25`（不要用斜杠，不要省略前导零）。"
            ),
        )
    )
    return _DEFAULT_DATE


def _parse_category(value: Any, issues: list[Issue]) -> Category:
    allowed = ", ".join(item.value for item in Category)
    if value is None:
        return _DEFAULT_CATEGORY
    text = str(value).strip()
    try:
        return Category(text)
    except ValueError:
        issues.append(
            Issue(
                rule=FM_INVALID_CATEGORY,
                field="category",
                message=(
                    f"category 取值不合法：`{text}`。允许的取值为：{allowed}（任务书 §16）。"
                    "修正方法：改成上述之一。"
                ),
            )
        )
        return _DEFAULT_CATEGORY


def _parse_status(value: Any, issues: list[Issue]) -> Status:
    allowed = ", ".join(item.value for item in Status)
    if value is None:
        return _DEFAULT_STATUS
    text = str(value).strip()
    try:
        return Status(text)
    except ValueError:
        issues.append(
            Issue(
                rule=FM_INVALID_STATUS,
                field="status",
                message=(
                    f"status 取值不合法：`{text}`。允许的取值为：{allowed}（任务书 §4）。"
                    "修正方法：改成上述之一，流转顺序见任务书 §17。"
                ),
            )
        )
        return _DEFAULT_STATUS


def _parse_tags(value: Any, issues: list[Issue]) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        # 任务书 §8.1 要求 tags 是字符串列表。容忍标量会让「漏掉一个连字符」
        # 这种错误静默通过，而 tags 是后续检索的主要依据，不能含糊。
        if value.strip():
            issues.append(
                Issue(
                    rule=FM_TAGS_NOT_LIST,
                    field="tags",
                    message=(
                        f"tags 应为列表，实际是一个字符串（`{value.strip()}`）。"
                        "修正方法：写成列表形式，标签之间用换行加连字符分隔：\n"
                        "    tags:\n"
                        "      - Humanoid\n"
                        "      - Robot Learning"
                    ),
                )
            )
        return ()
    if isinstance(value, (list, tuple)):
        tags: list[str] = []
        for item in value:
            if isinstance(item, str):
                if item.strip():
                    tags.append(item.strip())
            else:
                issues.append(
                    Issue(
                        rule=FM_TAG_NOT_STRING,
                        field="tags",
                        message=(
                            f"tags 中有非字符串项（{type(item).__name__}：`{item}`），已忽略。"
                            "修正方法：标签统一写成字符串，纯数字或含冒号的标签加引号。"
                        ),
                    )
                )
        return tuple(tags)
    issues.append(
        Issue(
            rule=FM_TAGS_NOT_LIST,
            field="tags",
            message=(
                f"tags 应为列表，实际为 {type(value).__name__}。"
                "修正方法：写成逐行列表：\n"
                "    tags:\n"
                "      - Humanoid\n"
                "      - Robot Learning"
            ),
        )
    )
    return ()


def _parse_platforms(value: Any, issues: list[Issue]) -> dict[str, bool]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        issues.append(
            Issue(
                rule=FM_PLATFORMS_NOT_MAPPING,
                field="platforms",
                message=(
                    f"platforms 应为映射，实际为 {type(value).__name__}。"
                    "修正方法：写成键值对，例如 `platforms:` 下逐行 `wechat: true`。"
                ),
            )
        )
        return {}

    platforms: dict[str, bool] = {}
    for key, raw in value.items():
        if not isinstance(raw, bool):
            issues.append(
                Issue(
                    rule=FM_TAG_NOT_BOOL,
                    field="platforms",
                    message=(
                        f"platforms.{key} 不是布尔值（实际 `{raw}`），已按真假转换。"
                        "修正方法：明确写成 `true` 或 `false`，避免 `yes`/`no` 这类 YAML 方言。"
                    ),
                )
            )
        platforms[str(key)] = bool(raw)

    if not platforms.get("wechat", False):
        issues.append(
            Issue(
                rule=FM_WECHAT_DISABLED,
                field="platforms",
                message=(
                    "platforms.wechat 必须为 true：当前阶段的目标平台就是微信公众号。"
                    "修正方法：在 platforms 下加 `wechat: true`。"
                ),
            )
        )
    return platforms


def _check_directory_name(source: Path | None, article_id: int) -> Issue | None:
    """校验目录名的序号与 ``id`` 是否一致（任务书 §3 的 ``002-light-o1`` 形式）。"""
    if source is None:
        return None

    match = ARTICLE_DIR_PATTERN.match(source.parent.name)
    if match is None:
        return Issue(
            rule=FM_DIR_NAME_FORMAT,
            line=1,
            message=(
                f"文章目录名 `{source.parent.name}` 不符合 `三位序号-slug` 的约定。"
                "修正方法：重命名为形如 `002-light-o1`；目录名同时也是产物目录名。"
            ),
        )

    directory_number = int(match.group("number"))
    if directory_number != article_id:
        return Issue(
            rule=FM_DIR_ID_MISMATCH,
            line=1,
            message=(
                f"目录名序号 `{directory_number:03d}` 与 front matter 的 id `{article_id}` 不一致。"
                "修正方法：统一两者，避免索引与产物目录排序错乱。"
            ),
        )
    return None
