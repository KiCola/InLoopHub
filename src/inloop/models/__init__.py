"""文章数据模型。

对外只暴露模型层需要的类型；解析细节在 :mod:`inloop.parser.frontmatter`。
"""

from inloop.models.article import (
    ARTICLE_DIR_PATTERN,
    REQUIRED_FIELDS,
    SLUG_PATTERN,
    Article,
    ArticleError,
    Category,
    Issue,
    Status,
)
from inloop.models.serializer import (
    FIELD_ORDER,
    SerializationError,
    article_meta,
    dump_front_matter,
    render_article_text,
    write_article,
)

# IssueLevel 的定义已归入 inloop.rules（规则表与级别同处一表）；此处转发以保持路径可用。
from inloop.rules import IssueLevel, Rule  # noqa: E402

__all__ = [
    "ARTICLE_DIR_PATTERN",
    "FIELD_ORDER",
    "REQUIRED_FIELDS",
    "SLUG_PATTERN",
    "Article",
    "ArticleError",
    "Category",
    "Issue",
    "IssueLevel",
    "Rule",
    "SerializationError",
    "Status",
    "article_meta",
    "dump_front_matter",
    "render_article_text",
    "write_article",
]
