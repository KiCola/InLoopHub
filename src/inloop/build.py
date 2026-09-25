"""构建编排：把一篇 Markdown 文章变成可交付的微信公众号产物。

职责：串起各模块，**不含具体转换逻辑**（那些在 parser / normalize / renderer / assets 内）。
本模块只回答「按什么顺序、用哪些参数、产出哪些文件、检查通过与否」。

产物结构（任务书 §8、§12、§13）：

    dist/wechat/<slug>/
    ├── article.html           要复制进公众号后台的正文
    ├── article.preview.html   手机宽度预览外壳，不用于发布
    ├── metadata.json          发布元数据，供将来平台接口复用
    ├── images/                正文图片实体文件
    └── cover.png              封面

两条纪律：

- **构建前必须校验通过。** 有 ERROR 就不产出任何文件：留下一个必然出问题的
  产物比什么都不产出更糟——它看起来能用。
- **不写时间戳到正文产物。** 只有 ``metadata.json`` 带生成时间，且支持用
  ``SOURCE_DATE_EPOCH`` 固定，使"同一输入两次构建逐字节一致"可以被验证。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from inloop.assets.pipeline import AssetError, AssetResult, ImageAsset, prepare_images
from inloop.config import Config, load_config
from inloop.fsutil import write_text
from inloop.models.article import Article
from inloop.normalize import normalize_html
from inloop.parser.markdown import render_markdown
from inloop.renderer.wechat import (
    StyleError,
    load_stylesheet,
    render_wechat_html,
    theme_name,
)
from inloop.rendering import RenderOptions, collect_render_options, theme_meta_tag

#: 产物根目录名（相对仓库根）
DIST_DIR = "dist"
#: 平台子目录名
WECHAT_DIR = "wechat"
#: 正文产物文件名
ARTICLE_HTML = "article.html"
#: 预览产物文件名
PREVIEW_HTML = "article.preview.html"
#: 元数据文件名
METADATA_JSON = "metadata.json"

#: 预览外壳的宽度（任务书 §13 要求模拟 375–430px 手机阅读宽度）
PREVIEW_WIDTH_PX = 430


class BuildError(RuntimeError):
    """构建失败。消息中必须包含修正建议。"""


@dataclass(slots=True)
class BuildOutcome:
    """构建结果。

    Attributes:
        output_dir: 产物目录。
        files: 产物文件相对路径列表（相对 output_dir）。
        images: 正文图片清单。``source_path`` 是仓库内源路径，
            ``output_relative`` 是产物内路径，供将来上传平台后回填正文。
        warnings: 非致命问题，必须展示给使用者。
        metadata: 写入 metadata.json 的内容。
    """

    output_dir: Path
    files: list[Path] = field(default_factory=list)
    images: list[ImageAsset] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, object] = field(default_factory=dict)


def build_article(
    article: Article,
    *,
    config: Config | None = None,
    article_dir: Path | None = None,
    root: Path | None = None,
    theme: str | None = None,
) -> BuildOutcome:
    """构建一篇微信公众号文章。

    Args:
        article: 文章模型。
        config: 配置；为 None 时自动加载。
        article_dir: 文章所在目录；为 None 时由 ``article.source`` 推断。
        root: 仓库根；为 None 时由配置推断。
        theme: 排版主题名；为 None 时取配置里的 ``wechat.theme``。

    Returns:
        构建结果。

    Raises:
        BuildError: 校验失败、配置缺失或素材处理出现致命问题。
    """
    resolved_config = config or load_config(root)
    repo_root = resolved_config.root
    resolved_article_dir = _resolve_article_dir(article, article_dir)

    if not article.is_valid:
        detail = "\n".join(f"  {issue.render(article.source)}" for issue in article.errors)
        raise BuildError(
            f"文章存在 {len(article.errors)} 个 ERROR，已中止构建（未产出任何文件）：\n"
            f"{detail}\n"
            f"修正方法：先运行 `inloop check {_short(article.source)}` 定位并修复问题。"
        )

    output_dir = repo_root / DIST_DIR / WECHAT_DIR / article.directory_name

    # 1) 正文 Markdown → HTML 片段
    rendered = render_markdown(article.body)
    warnings: list[str] = list(rendered.warnings)

    # 2) 结构规范化：脚注与公式降级、抽图片清单、剥离 id/class
    normalized = normalize_html(rendered.html)
    warnings.extend(normalized.warnings)

    # 3) 素材：校验并复制图片，得到「源路径 → 产物路径」映射
    warning_bytes = int(resolved_config.wechat_value("image_warning_bytes"))
    error_bytes = int(resolved_config.wechat_value("image_error_bytes"))
    try:
        assets = prepare_images(
            article_dir=resolved_article_dir,
            output_dir=output_dir,
            images=normalized.images,
            cover=article.cover,
            warning_bytes=warning_bytes,
            error_bytes=error_bytes,
        )
    except AssetError as exc:
        raise BuildError(str(exc)) from exc

    warnings.extend(assets.warnings)
    if assets.errors:
        detail = "\n".join(f"  {item}" for item in assets.errors)
        raise BuildError(
            f"素材校验未通过，已中止构建（未产出任何文件）：\n{detail}\n"
            f"修正方法：按上述提示修复后重新构建。"
        )

    # 4) 按素材映射改写正文中的图片路径
    rewritten_html = _rewrite_image_sources(normalized.html, assets.src_to_output)

    # 5) 加样式：CSS 内联 + 白名单清洗（顺带处理标题编号与落款区）
    active_theme = theme or theme_name(resolved_config)
    try:
        stylesheet = load_stylesheet(resolved_config, active_theme)
        wechat = render_wechat_html(
            rewritten_html,
            config=resolved_config,
            stylesheet=stylesheet,
            byline=article.byline,
            byline_note=article.byline_note,
        )
    except StyleError as exc:
        raise BuildError(str(exc)) from exc

    # 记录本次生效的渲染选项：样式会被不断调整，产物里不留记录就无法复现观感
    render_options = collect_render_options(
        resolved_config, theme=active_theme, stylesheet=stylesheet
    )

    warnings.extend(wechat.warnings)
    if wechat.unstyled_tags:
        warnings.append(
            f"以下标签没有匹配到任何样式：{'、'.join(wechat.unstyled_tags)}。"
            f"修正方法：检查 styles/wechat.css 是否缺少对应选择器。"
        )

    # 6) 落盘：全部内容准备好后一次性写入，避免中断留下半套产物
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata = build_metadata(
        article,
        repo_root=repo_root,
        image_paths=_image_relative_paths(assets),
        render_options=render_options,
    )

    files: list[Path] = []
    article_html = output_dir / ARTICLE_HTML
    preview_html = output_dir / PREVIEW_HTML
    metadata_json = output_dir / METADATA_JSON

    _write(
        article_html,
        _document(wechat.html, title=article.title, theme=active_theme),
    )
    _write(
        preview_html,
        _preview_document(wechat.html, title=article.title, theme=active_theme),
    )
    _write(metadata_json, json.dumps(metadata, ensure_ascii=False, indent=2) + "\n")

    # 产物清单一律使用**相对产物目录**的路径：绝对路径既会泄漏本机目录结构，
    # 也让清单无法跨机器复用（AGENTS.md §4 禁止写死绝对路径）。
    files.extend([Path(ARTICLE_HTML), Path(PREVIEW_HTML), Path(METADATA_JSON)])
    files.extend(asset.output_relative for asset in assets.assets)

    return BuildOutcome(
        output_dir=output_dir,
        files=sorted(set(files)),
        images=list(assets.assets),
        warnings=warnings,
        metadata=metadata,
    )


# --- 元数据 ---------------------------------------------------------------


def build_metadata(
    article: Article,
    *,
    repo_root: Path,
    image_paths: list[str],
    render_options: RenderOptions,
) -> dict[str, object]:
    """构造 ``metadata.json`` 的内容（任务书 §12）。

    键序固定：便于 diff，也便于将来自动化接口按稳定结构读取。
    ``render_options`` 记录本次生效的排版选项，使观感可复现。
    """
    source = article.source
    # 用绝对路径比较：article.source 可能是相对路径（取决于调用方怎么构造 Article），
    # 直接 relative_to 会抛 ValueError 而不是给出可读的错误。
    source_reference = ""
    if source is not None:
        try:
            source_reference = source.resolve().relative_to(repo_root.resolve()).as_posix()
        except ValueError:
            # 不在仓库内：保留原样总比崩掉好，同时这本身值得注意
            source_reference = source.as_posix()
    return {
        "title": article.title,
        "summary": article.summary,
        "author": article.author,
        "date": article.date.isoformat(),
        "cover": article.cover,
        "source": source_reference,
        "status": str(article.status),
        "platform": "wechat",
        "slug": article.directory_name,
        "category": str(article.category),
        "tags": list(article.tags),
        "images": image_paths,
        "byline": article.byline,
        "byline_note": article.byline_note,
        "render_options": render_options.as_metadata(),
        "generated_at": _generated_at(),
    }


def _generated_at() -> str:
    """生成时间。

    支持 ``SOURCE_DATE_EPOCH`` 固定取值，使"两次构建逐字节一致"可被验证。
    这是可复现构建的通行做法，而不是为测试开的特例。
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            moment = datetime.fromtimestamp(int(epoch), tz=UTC)
        except (TypeError, ValueError) as exc:
            raise BuildError(
                f"环境变量 SOURCE_DATE_EPOCH 取值非法：`{epoch}`。\n"
                f"修正方法：设为 Unix 秒数（整数），例如 1767225600；或删除该变量。"
            ) from exc
        return moment.astimezone().isoformat(timespec="seconds")
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _image_relative_paths(assets: AssetResult) -> list[str]:
    """取出产物中图片的相对路径，按处理顺序。"""
    return [asset.output_relative.as_posix() for asset in assets.assets]


# --- HTML 文档 ------------------------------------------------------------


def _document(body_html: str, *, title: str, theme: str) -> str:
    """生成完整的独立 HTML 文档（含 UTF-8 声明）。

    微信编辑器取的是其中的正文片段；声明编码是为了本地打开时不出现乱码。
    同时写入记录主题的 meta：样式会被不断调整，产物里留下主题名，
    才能回答"这个 HTML 是用哪套样式渲染的"。
    """
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        f"{theme_meta_tag(theme)}\n"
        f"<title>{_escape(title)}</title>\n"
        "</head>\n<body>\n"
        f"{body_html}\n"
        "</body>\n</html>\n"
    )


def _preview_document(body_html: str, *, title: str, theme: str) -> str:
    """生成手机宽度预览外壳（任务书 §13）。

    外壳样式**内联在元素上**，不引入外部 CSS——预览页必须能离线双击打开。
    正文本身的样式已在 ``body_html`` 内部，这里只负责给一个手机宽度的画布。
    """
    shell_style = (
        "margin:0;padding:0;background:#f0f0f3;"
        "font-family:-apple-system,BlinkMacSystemFont,'PingFang SC','Microsoft YaHei',sans-serif;"
    )
    frame_style = (
        f"max-width:{PREVIEW_WIDTH_PX}px;"
        "margin:0 auto;"
        "background:#ffffff;"
        "padding:20px 16px;"
        "min-height:100vh;"
        "box-sizing:border-box;"
    )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n<head>\n<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f"{theme_meta_tag(theme)}\n"
        f"<title>预览 · {_escape(title)}</title>\n"
        "</head>\n"
        f'<body style="{shell_style}">\n'
        f'<div style="{frame_style}">\n'
        f"{body_html}\n"
        "</div>\n"
        "</body>\n</html>\n"
    )


def _escape(text: str) -> str:
    """最小化 HTML 转义，仅用于 ``<title>``。"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _write(path: Path, content: str) -> Path:
    """写文本文件：UTF-8、LF、原子替换（带重试）。"""
    return write_text(path, content)


def _rewrite_image_sources(html: str, mapping: dict[str, str]) -> str:
    """按素材映射改写正文中的图片 ``src``。

    用 BeautifulSoup 而不是字符串替换：字符串替换会误伤正文里恰好与路径相同的文本。
    """
    if not mapping:
        return html

    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for image in soup.find_all("img"):
        src = image.get("src")
        if isinstance(src, str) and src in mapping:
            image["src"] = mapping[src]

    body = soup.body
    return "".join(str(child) for child in body.children) if body else str(soup)


def _resolve_article_dir(article: Article, article_dir: Path | None) -> Path:
    if article_dir is not None:
        return article_dir
    if article.source is not None:
        return article.source.parent
    raise BuildError(
        "无法确定文章目录：Article 既没有 source 也没有显式传入 article_dir。\n"
        "修正方法：从文件读取文章（Article.from_text(text, source=path)），"
        "或调用 build_article(..., article_dir=...)。"
    )


def _short(path: Path | None) -> str:
    return path.as_posix() if path is not None else "<内存>"
