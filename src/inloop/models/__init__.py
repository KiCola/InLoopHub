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
    IssueLevel,
    Status,
)

__all__ = [
    "ARTICLE_DIR_PATTERN",
    "REQUIRED_FIELDS",
    "SLUG_PATTERN",
    "Article",
    "ArticleError",
    "Category",
    "Issue",
    "IssueLevel",
    "Status",
]
