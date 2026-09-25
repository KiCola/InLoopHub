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

## 路径约定：两类，刻意不同（调用方必读）

本模块输出的路径分两类，**不要"统一风格"**——它们服务于不同用途：

**第一类：顶层"指针"字段 → 绝对路径**

    content_root / output_dir / html_path / preview_path / metadata_path

调用方（插件）要拿它**直接读写文件**，因此必须是可直接使用的绝对路径。
这些字段是**瞬态的**：只存在于这次命令的输出里，不落盘、不进入持久化产物。

**第二类：列表项内的路径 → 相对路径**

    articles[].path / images[].output / images[].source / metadata.source

这些会被记录、比对，将来还可能跨机器复用（例如上传图片后回填地址），
因此一律相对 ``content_root`` 书写。

**为什么不用同一种风格**：``AGENTS.md §4`` 要求"输出保持确定性"——
该约束针对的是**写入产物的内容**（``metadata.json`` 会被保存、比对、分享，
绝对路径会让同一篇文章在两台机器上产出不同字节）。
而本模块的输出是进程间消息，调用方按定义就在同一台机器上。

历史教训：本模块的文档曾写"路径一律相对 content_root，不写本机绝对路径"，
与实现矛盾。照文档实现的插件会以为无需处理绝对路径——这是独立审核发现的。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

from inloop.articles import ARTICLE_FILENAME, ArticleLocation, DeleteResult
from inloop.models.article import Article, Issue
from inloop.rules import IssueLevel

#: JSON 输出的格式版本。字段结构变化时递增，便于插件判断兼容性。
SCHEMA_VERSION = 1


#: 是否已经往 stdout 写过 JSON。用于检测"发出 JSON 之后又有东西写进 stdout"
#: 这类污染——它会让调用方 ``json.loads`` 报 ``Extra data``，把成功当失败。
_EMITTED = False


class JSONPollutedError(RuntimeError):
    """stdout 上被写入了非 JSON 内容，或写了多份 JSON。"""


def emit(payload: dict[str, Any]) -> None:
    """把结果写到 stdout。

    直接写 ``sys.stdout``：**不经 Rich**，因此不会有折行与颜色码。
    ``ensure_ascii=False`` 保留中文可读性；缩进让人手动调用时也能看。

    若在此之前已经输出过一份 JSON，说明某个调用点重复输出了——
    这时**立即报错**而不是继续写。stdout 上出现两份拼接内容会让调用方
    完全无法解析，比直接失败更难排查（AGENTS.md §4：不静默失败）。
    """
    global _EMITTED  # noqa: PLW0603 - 进程级状态，见上方说明

    if _EMITTED:
        raise JSONPollutedError(
            "试图向 stdout 输出第二份 JSON。\n"
            "修正方法：这是程序缺陷——每条命令只能有一个 JSON 出口。"
        )

    text = json.dumps(payload, ensure_ascii=False, indent=2)
    sys.stdout.write(text + "\n")
    sys.stdout.flush()
    _EMITTED = True


def mark_emitted() -> None:
    """标记"stdout 上已有内容"（供非 JSON 输出路径使用，避免重复输出）。"""
    global _EMITTED  # noqa: PLW0603 - 进程级状态
    _EMITTED = True


def reset() -> None:
    """清空输出状态，为下一次调用做准备。

    为什么需要：``_EMITTED`` 是进程级标记，而同一进程里可能调用多次
    （测试用 CliRunner 就是这样）。不重置的话第二次调用会被误判成
    "重复输出两份 JSON"而失败。

    状态只放在这一个模块里，避免"两处各记一个标记、各自以为对方负责"——
    ``cli.py`` 曾经也有一个同名标记，两处状态必须同步才不会出错。
    """
    global _EMITTED  # noqa: PLW0603 - 进程级状态
    _EMITTED = False


def already_emitted() -> bool:
    """stdout 上是否已经写过 JSON。"""
    return _EMITTED


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


def rel_to(path: Path | None, base: Path) -> str:
    """公开版 :func:`_rel`，供其他模块复用同一套相对路径写法。"""
    return _rel(path, base)


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
        "content_root": content_root.as_posix(),
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
        "content_root": content_root.as_posix(),
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
        "content_root": content_root.as_posix(),
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
    """删除前的预览。

    ``dry_run`` 标记这次**没有真的删除**——调用方据此区分两种情况：
    "我还没确认" 与 "删除失败了"。仅靠 ``removed: false`` 区分不出来
    （独立审核指出的问题）。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "removed": False,
        "dry_run": True,
        "dir_name": location.dir_name,
        "path": _rel(location.directory, base),
        "file_count": file_count,
        "image_count": image_count,
    }


def level_is_error(level: IssueLevel) -> bool:
    """级别判断集中一处，避免各调用点各写一遍。"""
    return level is IssueLevel.ERROR


def publish_payload(result: object, *, content_root: Path) -> dict[str, Any]:
    """发布到微信草稿箱的结果。

    ``uploaded_images`` 是「产物内路径 → 微信 URL」的完整映射：
    调用方据此知道哪些图已托管、正文里替换掉了几处。
    """
    from inloop.publishers.wechat_publish import PublishResult

    assert isinstance(result, PublishResult)
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "content_root": content_root.as_posix(),
        "draft_media_id": result.draft_media_id,
        "uploaded_images": result.uploaded_images,
        "uploaded_cover": result.uploaded_cover,
        "replaced_images": result.replaced_images,
        "published_html_path": (
            result.published_html_path.as_posix() if result.published_html_path else ""
        ),
        "warnings": list(result.warnings),
    }


def publish_status_payload(*, configured: bool, source: str = "") -> dict[str, Any]:
    """报告发布能力是否就绪（供界面决定显示哪种模式）。

    **未配置不是错误**：任务书 §18 的半自动流程本来就是默认状态。
    因此 ``ok`` 仍为 true，只用 ``configured`` 表达状态。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "configured": configured,
        "source": source,
    }


def misplaced_content_root_hint(content_root: Path) -> str:
    """如果内容目录看起来"传深了一层"，返回一句提示；否则返回空串。

    布局是 ``<content_root>/<年份>/<文章>/``。常见的误配有两种，且都很难自查
    （列表为空、但路径看起来"对"）：

    1. 传成了**年份目录**：``<content_root>/2026``
       —— 该目录自己就形如年份，且其中装的是文章目录
    2. 传成了**某篇文章目录**：``<content_root>/2026/001-xxx``
       —— 该目录里有 ``index.md``

    判据是**结构性**的，不是猜意图：这两位都恰好是本工具规定的层级
    （独立审核的建议，我认同这个区分）。
    """
    try:
        if _is_year_name(content_root.name):
            # 其下应当直接是文章目录（含 index.md），这正好印证是年份目录
            if any(
                (entry / ARTICLE_FILENAME).is_file()
                for entry in _safe_children(content_root)
            ):
                return (
                    f"传入了**年份目录**。内容目录应当是它的上一级："
                    f"{content_root.parent.as_posix()}"
                )

        if (content_root / ARTICLE_FILENAME).is_file():
            return (
                f"传入了**单个文章的目录**。内容目录应当是包含年份目录的那一层："
                f"{content_root.parent.parent.as_posix()}"
            )
    except OSError:
        return ""
    return ""


def _safe_children(directory: Path) -> list[Path]:
    """列出子目录；读不到时返回空列表而不是抛异常（提示逻辑不该让命令失败）。"""
    try:
        return [entry for entry in directory.iterdir() if entry.is_dir()]
    except OSError:
        return []


def _is_year_name(name: str) -> bool:
    """目录名是否形如年份（四位数字，且在合理范围内）。"""
    if len(name) != 4 or not name.isdigit():
        return False
    year = int(name)
    return 1900 <= year <= 2999


# --- 写操作与信息查询的结果 -----------------------------------------------


def new_article_payload(
    *,
    content_root: Path,
    dir_name: str,
    slug: str,
    title: str,
    article_id: int,
    status: str,
    path: str,
    cover: str,
) -> dict[str, Any]:
    """新建文章的结果。

    **必须返回新文章的路径**：调用方（插件）要立刻打开它。
    原先这个命令没有 JSON 输出，插件只能"create 之后再 list 一次去猜哪篇是新的"——
    多跑一次 Python 进程，而且并发时可能认错文章。

    ``content_root`` 与 :func:`list_payload` 一致地给出：
    调用方要靠它把相对 ``path`` 拼成可打开的位置
    （插件还要再把它转成 vault 内路径）。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "content_root": content_root.as_posix(),
        "dir_name": dir_name,
        "slug": slug,
        "title": title,
        "id": article_id,
        "status": status,
        # 相对内容目录，调用方自行拼接（与 articles[].path 同一约定）
        "path": path,
        "cover": cover,
    }


def status_payload(
    *,
    dir_name: str,
    slug: str,
    title: str,
    status: str,
    previous_status: str,
    path: str,
) -> dict[str, Any]:
    """修改状态的结果。

    ``previous_status`` 让调用方能在界面上回滚或提示"从 X 改到 Y"。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "dir_name": dir_name,
        "slug": slug,
        "title": title,
        "status": status,
        "previous_status": previous_status,
        "path": path,
    }


def info_payload(
    *,
    repo_root: Path,
    content_root: Path,
    content_source: str,
    dist_root: Path,
    site_name: str,
    site_author: str,
    brand_primary: str,
    article_count: int,
    next_id: int,
    templates: list[str],
) -> dict[str, Any]:
    """当前生效的配置概要。

    ``content_source`` 是**诊断的关键**：内容目录有四级来源，
    "以为在读 A、实际在读 B"是这套设计里最容易犯的错，
    因此把来源和值一起给出。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "repo_root": repo_root.as_posix(),
        "content_root": content_root.as_posix(),
        "content_source": content_source,
        "dist_root": dist_root.as_posix(),
        "site": {"name": site_name, "author": site_author},
        "brand": {"primary": brand_primary},
        "article_count": article_count,
        "next_id": next_id,
        "templates": templates,
    }


def themes_payload(themes: list[dict[str, str]]) -> dict[str, Any]:
    """可用排版主题。

    每项含 ``name`` / ``label`` / ``description`` / ``file``，
    供界面直接渲染成选择列表。
    """
    return {
        "ok": True,
        "schema": SCHEMA_VERSION,
        "count": len(themes),
        "themes": themes,
    }
