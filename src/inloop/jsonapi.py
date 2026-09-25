"""机器可读输出（任务书 §7.5）。

供编辑器插件等外部程序调用。核心设计约束：

1. **stdout 只含 JSON。** 人类可读的进度、提示、警告一律走 stderr。
   混在一起会让调用方无法直接 ``json.loads(stdout)``。
2. **不用 Rich 打印 JSON。** Rich 会按终端宽度折行、加 ANSI 颜色，
   两者都会破坏 JSON。这里用裸 ``sys.stdout.write``。
3. **字段名是稳定契约。** 改名等同于破坏性变更——插件依赖它们。
4. **失败也要给出结构化结果。** 命令失败时退出码非 0，同时 stdout 上
   仍是一份合法 JSON（``{"ok": false, "error": {...}}``），
   这样调用方不必去解析 stderr 的文本。

路径一律相对 ``content_root``（或产物目录），不写本机绝对路径——
与 metadata.json 的约定一致（AGENTS.md §4）。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from inloop.articles import ArticleLocation, DeleteResult
from inloop.models.article import Article, Issue
from inloop.rules import IssueLevel

#: JSON 输出的格式版本。字段结构变化时递增，便于插件判断兼容性。
SCHEMA_VERSION = 1


def emit(payload: dict[str, Any]) -> None:
    """把结果写到 stdout。

    直接写 ``sys.stdout``：**不经 Rich**，因此不会有折行与颜色码。
    ``ensure_ascii=False`` 保留中文可读性；缩进让人手动调用时也能看。
    """
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


def emit_error(code: str, message: str, *, hint: str = "") -> None:
    """输出结构化错误。

    Args:
        code: 机器可判断的错误类型，形如 ``content_root_missing``。
        message: 人可读的说明。
        hint: 修正建议（对应人类输出里的"修正方法"，插件可直接展示）。
    """
    error: dict[str, Any] = {"code": code, "message": message}
    if hint:
        error["hint"] = hint
    emit({"ok": False, "schema": SCHEMA_VERSION, "error": error})


def issue_to_dict(issue: Issue, *, base: Path, file: Path | None = None) -> dict[str, Any]:
    """把一条校验问题转成 JSON 对象。

    字段含义：

    - ``code`` / ``message``：规则码与说明，说明里含"怎么改"
    - ``field``：涉及的 front matter 字段（与字段无关时为 null）
    - ``line``：源文件行号（无法定位时为 null）
    - ``file``：**相对内容目录**的路径，插件据此定位到具体文件

    这里的路径刻意不写绝对路径：插件在同一个 vault 里工作，
    相对路径足够定位，而绝对路径既泄漏目录结构又无法跨机器复用。
    """
    return {
        "code": issue.code,
        "level": issue.level.value,
        "message": issue.message,
        "field": issue.field,
        "line": issue.line,
        "file": _rel(file, base),
    }


def _rel(path: Path | None, base: Path) -> str:
    """把路径写成相对 ``base`` 的形式；算不出时返回空串。"""
    if path is None:
        return ""
    try:
        return path.resolve().relative_to(base.resolve()).as_posix()
    except ValueError:
        return ""


def article_to_dict(article: Article, location: ArticleLocation, *, base: Path) -> dict[str, Any]:
    """把一篇文章转成 JSON 对象。

    ``parsable`` 恒为 true（无法解析的条目走 :func:`unparsable_to_dict`）。
    """
    return {
        "id": article.id,
        "dir_name": location.dir_name,
        "slug": location.slug or "",
        "title": article.title,
        "date": article.date.isoformat(),
        "category": str(article.category),
        "category_label": article.category.label,
        "status": str(article.status),
        "tags": list(article.tags),
        "summary": article.summary,
        "path": _rel(location.index, base),
        "parsable": True,
        "errors": [
            issue_to_dict(i, base=base, file=location.index) for i in article.errors
        ],
        "warnings": [
            issue_to_dict(i, base=base, file=location.index) for i in article.warnings
        ],
    }


def unparsable_to_dict(location: ArticleLocation, *, base: Path, reason: str) -> dict[str, Any]:
    """无法解析的文章条目。"""
    return {
        "id": location.number or 0,
        "dir_name": location.dir_name,
        "slug": location.slug or "",
        "title": "",
        "date": "",
        "category": "",
        "category_label": "",
        "status": "",
        "tags": [],
        "summary": "",
        "path": _rel(location.index, base),
        "parsable": False,
        "reason": reason,
        "errors": [],
        "warnings": [],
    }


def check_payload(
    article: Article, location: ArticleLocation, *, base: Path
) -> dict[str, Any]:
    """单篇检查结果。"""
    return {
        "ok": not article.errors,
        "schema": SCHEMA_VERSION,
        "article": article_to_dict(article, location, base=base),
        "error_count": len(article.errors),
        "warning_count": len(article.warnings),
    }


def check_all_payload(
    items: list[dict[str, Any]],
    *,
    content_root: Path,
    error_count: int,
    warning_count: int,
    unparsable: int,
) -> dict[str, Any]:
    """全部文章的检查结果。"""
    return {
        "ok": error_count == 0,
        "schema": SCHEMA_VERSION,
        "content_root": str(content_root),
        "total": len(items),
        "error_count": error_count,
        "warning_count": warning_count,
        "unparsable": unparsable,
        "articles": items,
    }


def list_payload(
    items: list[dict[str, Any]], *, content_root: Path, next_id: int
) -> dict[str, Any]:
    """文章列表。"""
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "content_root": str(content_root),
        "count": len(items),
        "next_id": next_id,
        "articles": items,
    }


def build_payload(outcome: object, *, content_root: Path) -> dict[str, Any]:
    """构建结果。

    包含正文 HTML 的**产物路径**与图片顺序清单：插件要据此做"复制到公众号"
    与"逐张上传图片"，不能靠再解析 HTML 反推。
    """
    from inloop.build import BuildOutcome

    assert isinstance(outcome, BuildOutcome)
    metadata = outcome.metadata
    images = metadata.get("images", [])
    body_images = [
        entry
        for entry in images
        if isinstance(entry, dict) and entry.get("kind") == "body"
    ]

    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "content_root": str(content_root),
        "output_dir": outcome.output_dir.as_posix(),
        "files": [p.as_posix() for p in outcome.files],
        "html_path": (outcome.output_dir / "article.html").as_posix(),
        "preview_path": (outcome.output_dir / "article.preview.html").as_posix(),
        "metadata_path": (outcome.output_dir / "metadata.json").as_posix(),
        "images": images,
        "body_images": body_images,
        "warnings": list(outcome.warnings),
        "metadata": metadata,
    }


def delete_payload(result: DeleteResult, *, base: Path, removed: bool) -> dict[str, Any]:
    """删除结果。``removed: false`` 表示用户（或非交互环境）取消了删除。"""
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "removed": removed,
        "dir_name": result.location.dir_name,
        "path": _rel(result.location.directory, base),
        "files": list(result.files),
        "image_count": result.image_count,
        "total_bytes": result.total_bytes,
    }


def deletion_preview_payload(
    location: ArticleLocation, *, base: Path, image_count: int, file_count: int
) -> dict[str, Any]:
    """删除前的预览（取消时把这份数据返回给调用方）。"""
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "removed": False,
        "dir_name": location.dir_name,
        "path": _rel(location.directory, base),
        "file_count": file_count,
        "image_count": image_count,
    }


def level_is_error(level: IssueLevel) -> bool:
    """级别判断集中一处，避免各调用点各写一遍。"""
    return level is IssueLevel.ERROR
