"""发布前检查：复用构建检查，汇总为可定位的诊断；不写源文件或产物。"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Any

from inloop.articles import ArticleLocation
from inloop.build import inspect_content
from inloop.config import Config
from inloop.jsonapi import check_payload
from inloop.models.article import Article, Issue
from inloop.parser.frontmatter import parse_front_matter
from inloop.rules import get_rule

_DIAGNOSTIC = re.compile(r"\b((?:IMG|MD)\d{3}) \[(?:ERROR|WARNING)\]\s*(.*)", re.S)
_REFERENCE = re.compile(r"`([^`]+)`")

MANUAL_CHECKS: tuple[str, ...] = (
    "检查是否仍有模板占位文字、TODO 或未完成的段落。",
    "复制到微信后逐张上传正文图片，并单独设置封面、标题、作者和摘要。",
    "在微信手机预览中确认代码缩进、公式、表格、图片与链接；本机检查不代表微信端通过。",
)


def publication_check(
    article: Article, location: ArticleLocation, config: Config, source: str
) -> dict[str, Any]:
    """返回单篇检查信封；保留既有字段，附带人工复核清单。"""
    inspected = inspect_content(article, config, location.directory)
    issues = list(article.issues)
    for message in inspected.errors + inspected.warnings:
        match = _DIAGNOSTIC.search(message)
        if match is None:
            raise ValueError(f"检查提示缺少规则码：{message}。修正方法：在对应检查中补齐规则码。")
        rule = get_rule(match.group(1))
        field = "cover" if rule.code == "IMG003" or match.group(2).startswith("封面") else None
        issues.append(Issue(rule, match.group(2), field=field))

    front = parse_front_matter(source)
    lines = source.splitlines()
    located = [replace(issue, line=_locate(issue, lines, front.body_offset)) for issue in issues]
    checked = replace(article, issues=tuple(located))
    # 此处 location 的两级父目录就是内容根，不使用工具仓库根。
    base = location.directory.parent.parent
    payload = check_payload(checked, location, base=base)
    payload["manual_checks"] = list(MANUAL_CHECKS)
    return payload


def _locate(issue: Issue, lines: list[str], body_offset: int) -> int | None:
    """仅在位置明确时返回行号；重复引用不猜行，界面退回打开文章。"""
    if issue.field:
        field = issue.field.split(".")[0]
        pattern = re.compile(rf"^{re.escape(field)}\s*:")
        for number, line in enumerate(lines[:body_offset - 1], start=1):
            if pattern.match(line):
                return number
        return 1
    if issue.code.startswith("IMG"):
        for reference in _REFERENCE.findall(issue.message):
            matches = [
                number for number, line in enumerate(lines, start=1)
                if number >= body_offset and reference in line
            ]
            if len(matches) == 1:
                return matches[0]
    return issue.line
