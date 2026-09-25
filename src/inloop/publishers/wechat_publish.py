"""把已构建的文章发布到微信公众号草稿箱（任务书 §19、§25 第 18–19 项）。

## 流程

1. 用构建产物里的图片清单，逐张上传到微信，换取微信托管的 URL
2. 把正文 HTML 里的本地路径**替换**成那些 URL
3. 上传封面为永久素材，拿到 ``thumb_media_id``
4. 创建草稿（**不群发**，任务书 §18）

## 为什么要"替换"而不是"重新渲染"

构建产物已经带好了「源路径 → 产物路径」的映射，以及正文里实际使用的 ``src``
（见 ``publishers/base.py`` 的 :class:`ImageRef`）。因此这里只做字符串替换，
**不反向解析 HTML**——那正是 AGENTS.md §11 第 2 条要求避免的事。

## 没有凭据时

:func:`publish_article` 会在缺凭据时抛 :class:`PublishNotConfigured`，
由调用方降级为"复制到公众号"的半自动流程。**没有凭据不是错误**，
它是任务书 §18 描述的默认状态。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from inloop.publishers.wechat_api import (
    WechatClient,
    WechatCredentials,
    WechatError,
    load_credentials,
)


class PublishNotConfigured(WechatError):
    """没有配置公众号凭据，无法调用 API。

    单独一个类型，是为了让调用方能明确区分"没配置"与"调用失败"——
    前者应当引导用户去配置，后者才需要展示错误细节。
    """

    def __init__(self) -> None:
        super().__init__(
            "没有配置微信公众号凭据，无法自动上传。",
            code="publish_not_configured",
            hint=(
                "两种方式任选其一：\n"
                "  1. 设置环境变量 INLOOP_WECHAT_APPID 与 INLOOP_WECHAT_SECRET\n"
                "  2. 创建 config/wechat.credentials.json，内容形如\n"
                '     {"appid": "wx...", "secret": "..."}\n'
                "凭据在公众号后台「设置与开发 → 基本配置」里查看。\n"
                "注意：还需要把本机出口 IP 加入后台的 IP 白名单。\n"
                "在此之前，可以用 `inloop build-wechat` + 手动粘贴（见发布指南）。"
            ),
        )


@dataclass
class PublishResult:
    """发布结果。

    Attributes:
        draft_media_id: 微信返回的草稿 media_id。
        uploaded_images: ``产物内路径 → 微信 URL``，供排查与复用。
        uploaded_cover: 封面素材的 ``media_id``。
        replaced_images: 正文里被替换掉的 ``src`` 数量。
        published_html_path: 回填了微信 URL 的 HTML 保存位置；为 None 表示未保存。
        warnings: 非致命问题。
    """

    draft_media_id: str
    uploaded_images: dict[str, str] = field(default_factory=dict)
    uploaded_cover: str = ""
    replaced_images: int = 0
    published_html_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


#: 回填微信 URL 后的 HTML 文件名。
#: 保留它是为了"接口能用但草稿不满意"时仍可手工粘贴——把自动化的收益
#: 变成额外选项，而不是唯一路径。
PUBLISHED_HTML_NAME = "article.published.html"


def credentials_available(repo_root: Path) -> bool:
    """凭据是否已配置（用于在界面上决定显示哪种模式）。"""
    try:
        return load_credentials(repo_root) is not None
    except WechatError:
        # 凭据文件格式错误时也当作"未就绪"——界面会走复制模式，
        # 用户主动调用 publish 时会拿到具体的格式错误。
        return False


def rewrite_image_sources(html: str, mapping: dict[str, str]) -> tuple[str, int]:
    """把正文里的图片路径替换成微信托管的 URL。

    ``mapping`` 的键是正文里**实际出现的** ``src`` 值（relative form），
    因此直接做字符串替换即可，不需要解析 HTML。

    Returns:
        ``(替换后的 HTML, 实际替换的次数)``。
    """
    replaced = 0
    result = html
    for source, url in mapping.items():
        if not source or source == url:
            continue
        count = result.count(source)
        if count:
            result = result.replace(source, url)
            replaced += count
    return result, replaced


def publish_article(
    *,
    repo_root: Path,
    metadata: dict[str, object],
    output_dir: Path,
    html_path: Path,
    client: WechatClient | None = None,
    credentials: WechatCredentials | None = None,
) -> PublishResult:
    """把一篇已构建的文章发到公众号草稿箱。

    Args:
        repo_root: 工具仓库根（定位凭据文件）。
        metadata: 构建产物的 ``metadata.json`` 内容。
        output_dir: 产物目录（图片在这里）。
        html_path: 正文 HTML 的路径。
        client: 注入用；为 None 时按凭据创建。
        credentials: 显式凭据；为 None 时从环境变量/文件读取。

    Returns:
        发布结果。

    Raises:
        PublishNotConfigured: 没有凭据。
        WechatError: 调用失败。
    """
    if client is None:
        resolved = load_credentials(repo_root, explicit=credentials)
        if resolved is None:
            raise PublishNotConfigured()
        client = WechatClient(credentials=resolved)

    warnings: list[str] = []
    uploaded: dict[str, str] = {}

    images = metadata.get("images")
    if not isinstance(images, list):
        images = []

    # 1) 正文图片：逐张上传换 URL
    mapping: dict[str, str] = {}
    for entry in images:
        if not isinstance(entry, dict) or entry.get("kind") != "body":
            continue
        output = str(entry.get("output", ""))
        if not output:
            continue
        path = output_dir / output
        try:
            url = client.upload_body_image(path)
        except WechatError as exc:
            # 一张图失败就整体中止：产出半套正文比报错更糟
            raise WechatError(
                f"上传正文图片失败：{output}\n原始错误：{exc}",
                code=exc.code,
                errcode=exc.errcode,
                hint=exc.hint,
            ) from exc
        uploaded[output] = url
        # 正文里用的是产物内的相对路径，与其 ``output`` 字段一致
        mapping[output] = url

    html = html_path.read_text(encoding="utf-8")
    rewritten, replaced = rewrite_image_sources(html, mapping)
    if mapping and replaced == 0:
        warnings.append(
            "上传了图片但没有在正文里找到对应的 src，图片可能不会显示。"
            "请确认正文 HTML 里的图片路径与 metadata 的 images[].output 一致。"
        )

    # 2) 封面：必须是永久素材，草稿的 thumb_media_id 用它
    cover_output = ""
    for entry in images:
        if isinstance(entry, dict) and entry.get("kind") == "cover":
            cover_output = str(entry.get("output", ""))
            break

    if not cover_output:
        raise WechatError(
            "产物里没有封面，无法创建草稿（微信要求草稿必须有封面）。",
            code="cover_missing",
            hint="确认 front matter 的 cover 字段指向一个存在的图片文件。",
        )

    thumb_media_id = client.upload_cover_material(output_dir / cover_output)

    # 3) 建草稿（不群发）
    media_id = client.add_draft(
        title=str(metadata.get("title", "")),
        html=rewritten,
        thumb_media_id=thumb_media_id,
        author=str(metadata.get("author", "")),
        digest=str(metadata.get("summary", "")),
    )

    # 4) 把回填后的 HTML 也落盘。
    # 理由：接口能用但草稿不满意时，人仍可打开这个文件手工粘贴，图片已经是
    # 微信自己的 URL，粘过去直接能显示。把自动化的收益变成**额外选项**而不是唯一路径。
    published_path = output_dir / PUBLISHED_HTML_NAME
    try:
        from inloop.fsutil import write_text

        write_text(published_path, rewritten)
    except OSError as exc:
        published_path = None
        warnings.append(f"回填后的 HTML 没能保存（不影响草稿）：{exc}")

    return PublishResult(
        draft_media_id=media_id,
        uploaded_images=uploaded,
        uploaded_cover=thumb_media_id,
        replaced_images=replaced,
        published_html_path=published_path,
        warnings=warnings,
    )
