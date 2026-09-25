"""素材（图片）处理流水线。

职责边界（AGENTS.md §7、docs/architecture.md 第 5 节）：

- **负责**：扫描文章引用的图片、校验（存在性/格式/绝对路径/体积）、复制到产物目录、
  产出结构化的图片清单。
- **不负责**：决定正文 HTML 里 ``src`` 该怎么写。这里只给出「源路径 → 产物相对路径」
  的映射，由调用方据此统一改写 HTML——同一件事只在一个地方做。

设计约束（AGENTS.md §11 第 2 条）：图片必须以**独立文件**进入产物并带清单，
供将来上传到平台换取地址后回填正文。禁止内联成 data URI。
"""

from __future__ import annotations

import shutil
import struct
from dataclasses import dataclass, field
from pathlib import Path

from inloop.normalize import ExtractedImage
from inloop.rules import (
    IMG_ABSOLUTE_PATH,
    IMG_COVER_MISSING,
    IMG_EXTERNAL,
    IMG_MISSING,
    IMG_MISSING_ALT,
    IMG_MISSING_CAPTION,
    IMG_TOO_LARGE_ERROR,
    IMG_TOO_LARGE_WARNING,
    IMG_UNSUPPORTED_FORMAT,
    Rule,
)

#: 产物中存放图片的子目录名
IMAGES_DIR_NAME = "images"

#: 支持的图片格式（任务书 §11）
SUPPORTED_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg", ".gif", ".webp"})

#: 允许优化的格式；GIF 保持原样以保留动画
OPTIMIZABLE_SUFFIXES: frozenset[str] = frozenset({".png", ".jpg", ".jpeg"})


@dataclass(frozen=True, slots=True)
class ImageAsset:
    """一张待处理的图片。

    Attributes:
        source_path: 仓库内的原始图片路径。
        output_relative: 产物中的相对路径（相对产物根，形如 ``images/a.png``）。
        alt: 替代文字。
        title: 图片说明。
        from_markdown: 来自正文（True）还是封面等元数据（False）。
        section: 该图所属的最近一个上级标题文本；供人工插图时定位。
        byte_size: 文件字节数，写入清单供发布前判断体积。
        width / height: 像素尺寸；解析不出时为 0。
    """

    source_path: Path
    output_relative: Path
    alt: str = ""
    title: str = ""
    from_markdown: bool = True
    section: str = ""
    byte_size: int = 0
    width: int = 0
    height: int = 0

    @property
    def html_src(self) -> str:
        """正文 HTML 中应当使用的 ``src`` 值。"""
        return self.output_relative.as_posix()


@dataclass(slots=True)
class AssetResult:
    """素材处理结果。

    Attributes:
        assets: 全部已就位的图片，按处理顺序。
        src_to_output: 原始 ``src`` → 正文中应使用的 ``src``。
        warnings: 非致命问题，构建继续但必须展示。
        errors: 致命问题，构建必须中止。
    """

    assets: list[ImageAsset] = field(default_factory=list)
    src_to_output: dict[str, str] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """是否没有致命问题。"""
        return not self.errors


class AssetError(ValueError):
    """素材处理出现致命问题。"""


def prepare_images(
    *,
    article_dir: Path,
    output_dir: Path,
    images: tuple[ExtractedImage, ...],
    cover: str,
    warning_bytes: int,
    error_bytes: int,
) -> AssetResult:
    """把文章引用的图片复制到产物目录。

    Args:
        article_dir: 文章目录，用于解析正文里的相对路径。
        output_dir: 产物根目录（``dist/wechat/<slug>/``）。
        images: 正文中出现的图片。
        cover: 封面文件名，相对文章目录。
        warning_bytes: 体积告警阈值。
        error_bytes: 体积错误阈值。

    Returns:
        处理结果。**致命问题被收集在 ``errors`` 而不是立刻抛出**，
        这样一次构建能报出全部素材问题，而不是让人改一张跑一次。
    """
    result = AssetResult()
    images_dir = output_dir / IMAGES_DIR_NAME
    used_names: dict[str, Path] = {}
    # 同一张图可能被引用多次；只复制一次，后续引用直接复用产物路径
    copied: dict[Path, ImageAsset] = {}

    for image in images:
        if not image.is_local:
            # 外部图片不复制、不改写，但**必须告警**：实测微信公众号编辑器
            # 不会抓取外链图片，粘贴后只显示成一串文字，图片等于丢失。
            # 曾经这里写着"编辑器会自行处理外链图片"——那是错的，已按实测更正。
            result.warnings.append(
                f"{_rel(article_dir)} {IMG_EXTERNAL.code} [{IMG_EXTERNAL.level.value}] "
                f"正文引用了外链图片：`{image.src}`。"
                f"微信编辑器不会抓取外链图片，粘贴后只显示为文字。"
                f"修正方法：把图片下载到文章目录的 `assets/` 下，改用相对路径引用。"
            )
            continue

        absolute_issue = _check_absolute(image.src, article_dir)
        if absolute_issue is not None:
            result.errors.append(absolute_issue)
            continue

        source = _resolve(article_dir, image.src)

        existing = copied.get(source)
        if existing is not None:
            # 已复制过：沿用产物路径，但本次引用的 alt/title 仍然要单独校验，
            # 否则「同一张图第一次带 alt、第二次没带」会被漏报。
            _check_caption(image, source, result)
            result.src_to_output[image.src] = existing.output_relative.as_posix()
            continue

        if not _collect_source_issues(source, image, result, warning_bytes, error_bytes):
            continue

        try:
            output_name = _unique_name(source.name, source, used_names)
        except AssetError as exc:
            # 收集而不是抛出：一次构建要能报出全部素材问题
            result.errors.append(str(exc))
            continue

        destination = images_dir / output_name
        _copy(source, destination)

        size = image_size(destination)
        asset = ImageAsset(
            source_path=source,
            output_relative=Path(IMAGES_DIR_NAME) / output_name,
            alt=image.alt,
            title=image.title,
            from_markdown=True,
            section=image.section,
            byte_size=destination.stat().st_size,
            width=size[0] if size else 0,
            height=size[1] if size else 0,
        )
        copied[source] = asset
        result.assets.append(asset)
        result.src_to_output[image.src] = asset.output_relative.as_posix()

    _prepare_cover(article_dir=article_dir, output_dir=output_dir, cover=cover, result=result)
    return result


def _check_absolute(src: str, article_dir: Path) -> str | None:
    """检查是否使用了绝对路径（任务书 §5 明确禁止）。"""
    lowered = src.lower()
    looks_absolute = (
        lowered.startswith(("file://", "/", "\\"))
        or (len(src) > 1 and src[1] == ":" and src[0].isalpha())  # C:\ 之类
    )
    if looks_absolute:
        return (
            f"{_rel(article_dir)} {IMG_ABSOLUTE_PATH.code} [{IMG_ABSOLUTE_PATH.level.value}] "
            f"图片使用了绝对路径：`{src}`。"
            f"修正方法：改为相对文章目录的路径，例如 `assets/{Path(src).name}`。"
        )
    return None


def _collect_source_issues(
    source: Path,
    image: ExtractedImage,
    result: AssetResult,
    warning_bytes: int,
    error_bytes: int,
) -> bool:
    """校验单个图片文件，返回是否可以继续处理。"""
    if not source.is_file():
        result.errors.append(
            f"{_rel(source)} {IMG_MISSING.code} [{IMG_MISSING.level.value}] "
            f"正文引用的本地图片不存在：`{image.src}`。"
            f"修正方法：把图片放到该位置，或改正正文中的路径。"
        )
        return False

    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        allowed = "/".join(sorted(s.lstrip(".") for s in SUPPORTED_SUFFIXES))
        shown = suffix or "（无扩展名）"
        result.errors.append(
            f"{_rel(source)} {IMG_UNSUPPORTED_FORMAT.code} "
            f"[{IMG_UNSUPPORTED_FORMAT.level.value}] 图片格式不受支持：`{shown}`。"
            f"修正方法：转换为 {allowed} 之一。"
        )
        return False

    size = source.stat().st_size
    if size > error_bytes:
        result.errors.append(
            f"{_rel(source)} {IMG_TOO_LARGE_ERROR.code} "
            f"[{IMG_TOO_LARGE_ERROR.level.value}] 图片 {_human(size)} 超过上限 "
            f"{_human(error_bytes)}。"
            f"修正方法：压缩图片，公众号单图建议控制在 {_human(warning_bytes)} 以内。"
        )
    elif size > warning_bytes:
        result.warnings.append(
            f"{_rel(source)} {IMG_TOO_LARGE_WARNING.code} "
            f"[{IMG_TOO_LARGE_WARNING.level.value}] 图片体积偏大：{_human(size)}"
            f"（建议小于 {_human(warning_bytes)}）。修正方法：压缩后替换。"
        )

    _check_caption(image, source, result)
    if not image.title:
        result.warnings.append(
            f"{_rel(source)} {IMG_MISSING_CAPTION.code} "
            f"[{IMG_MISSING_CAPTION.level.value}] 图片缺少 title（caption）：`{image.src}`。"
            f'修正方法：写成 `![alt]({image.src} "图注")` 可为图片补一句说明。'
        )
    return True


def _check_caption(image: ExtractedImage, source: Path, result: AssetResult) -> None:
    """只校验与文件本身无关的问题（alt）。

    同一张图可能被多次引用，而每次引用写的 alt 未必相同，
    因此这项检查不能与「文件是否已复制」合并，否则第二次的空 alt 会被漏报。
    """
    if not image.alt:
        result.warnings.append(
            f"{_rel(source)} {IMG_MISSING_ALT.code} [{IMG_MISSING_ALT.level.value}] "
            f"正文图片缺少 alt 文字：`{image.src}`。"
            f"修正方法：写成 `![图片说明]({image.src})`，alt 会作为图片说明显示。"
        )


def _prepare_cover(
    *, article_dir: Path, output_dir: Path, cover: str, result: AssetResult
) -> None:
    """把封面复制到产物根目录。"""
    if not cover.strip():
        result.errors.append(
            f"{_rel(article_dir)} {IMG_COVER_MISSING.code} "
            f"[{IMG_COVER_MISSING.level.value}] front matter 的 cover 为空。"
            f"修正方法：填入封面文件名，例如 `cover.png`。"
        )
        return

    source = _resolve(article_dir, cover)
    if not source.is_file():
        result.errors.append(
            f"{_rel(source)} {IMG_COVER_MISSING.code} "
            f"[{IMG_COVER_MISSING.level.value}] 封面文件不存在：`{cover}`。"
            f"修正方法：把封面放到文章目录下，或修正 front matter 中的 cover。"
        )
        return

    suffix = source.suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        result.errors.append(
            f"{_rel(source)} {IMG_UNSUPPORTED_FORMAT.code} "
            f"[{IMG_UNSUPPORTED_FORMAT.level.value}] 封面格式不受支持：`{suffix}`。"
            f"修正方法：转换为 png/jpg/jpeg/gif/webp 之一。"
        )
        return

    destination = output_dir / source.name
    _copy(source, destination)
    size = image_size(destination)
    result.assets.append(
        ImageAsset(
            source_path=source,
            output_relative=Path(source.name),
            alt="封面",
            title="",
            from_markdown=False,
            byte_size=destination.stat().st_size,
            width=size[0] if size else 0,
            height=size[1] if size else 0,
        )
    )


# --- 辅助 -----------------------------------------------------------------


def _resolve(article_dir: Path, reference: str) -> Path:
    """把正文中的相对路径解析为绝对路径。

    使用 ``resolve()`` 而非简单拼接：正文里可能写 ``./assets/../assets/a.png``，
    规范化后再判断存在性才不会误判。
    """
    return (article_dir / reference).resolve()


def _unique_name(name: str, source: Path, used: dict[str, Path]) -> str:
    """为产物中的图片取一个不冲突的文件名。

    不同目录下的同名图片（如两篇都叫 ``architecture.png``）在产物里会被压平到
    同一层。若直接复制，后一张会静默覆盖前一张，正文里两张图都显示成同一张——
    这种错误很难被发现，因此这里明确报错，让使用者自己决定怎么改。
    """
    existing = used.get(name)
    if existing is None or existing == source:
        used[name] = source
        return name

    raise AssetError(
        f"产物中的图片文件名冲突：`{name}`\n"
        f"  来源一：{existing}\n"
        f"  来源二：{source}\n"
        f"修正方法：把其中一张改名（例如 `architecture-1.png`），"
        f"并同步修改正文中的引用。产物目录是平铺的，同名会互相覆盖。"
    )


def _copy(source: Path, destination: Path) -> None:
    """复制文件，自动创建目标目录。"""
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _rel(path: Path) -> str:
    """尽量给出简短可读的路径，用于提示信息。"""
    parts = path.parts
    if len(parts) > 3:
        return "/".join(parts[-3:])
    return path.as_posix()


def _human(size: int) -> str:
    """把字节数变成人读形式。"""
    value = float(size)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f}{unit}" if unit != "B" else f"{int(value)}B"
        value /= 1024
    return f"{value:.1f}GB"


def image_size(path: Path) -> tuple[int, int] | None:
    """读取图片的宽高（像素）。

    只解析文件头，不整体解码——构建时不需要像素数据，只需尺寸用于记录与告警。
    GIF/PNG/JPEG/WebP 的头部结构各不相同，这里实现最小解析；
    解析不出时返回 None，由调用方决定是否给出提示。
    """
    try:
        with path.open("rb") as handle:
            head = handle.read(32)
            if head.startswith(b"\x89PNG\r\n\x1a\n"):
                width, height = struct.unpack(">II", head[16:24])
                return int(width), int(height)
            if head[:3] == b"GIF":
                width, height = struct.unpack("<HH", head[6:10])
                return int(width), int(height)
            if head.startswith(b"\xff\xd8"):
                return _jpeg_size(path)
            if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
                return _webp_size(path)
    except (OSError, struct.error):
        return None
    return None


def _jpeg_size(path: Path) -> tuple[int, int] | None:
    """扫描 JPEG 段找 SOF 标记以取得尺寸。"""
    with path.open("rb") as handle:
        handle.read(2)  # SOI
        while True:
            marker = handle.read(2)
            if len(marker) < 2:
                return None
            if marker[0] != 0xFF:
                return None
            code = marker[1]
            if code in (0xD8, 0xD9) or 0xD0 <= code <= 0xD7:
                continue
            length_bytes = handle.read(2)
            if len(length_bytes) < 2:
                return None
            length = struct.unpack(">H", length_bytes)[0]
            if 0xC0 <= code <= 0xCF and code not in (0xC4, 0xC8, 0xCC):
                payload = handle.read(5)
                if len(payload) < 5:
                    return None
                height, width = struct.unpack(">HH", payload[1:5])
                return int(width), int(height)
            handle.seek(length - 2, 1)


def _webp_size(path: Path) -> tuple[int, int] | None:
    """解析 WebP 的 VP8/VP8L/VP8X 三种头部。"""
    with path.open("rb") as handle:
        handle.seek(12)
        chunk = handle.read(4)
        if chunk == b"VP8 ":
            handle.read(6)
            data = handle.read(4)
            if len(data) < 4:
                return None
            width = struct.unpack("<H", data[0:2])[0] & 0x3FFF
            height = struct.unpack("<H", data[2:4])[0] & 0x3FFF
            return width, height
        if chunk == b"VP8L":
            handle.read(1)
            data = handle.read(4)
            if len(data) < 4:
                return None
            bits = struct.unpack("<I", data)[0]
            width = (bits & 0x3FFF) + 1
            height = ((bits >> 14) & 0x3FFF) + 1
            return width, height
        if chunk == b"VP8X":
            handle.read(4)
            data = handle.read(6)
            if len(data) < 6:
                return None
            width = int.from_bytes(data[0:3], "little") + 1
            height = int.from_bytes(data[3:6], "little") + 1
            return width, height
    return None


def describe_rule(rule: Rule) -> str:
    """把规则渲染成 ``码 [级别] 说明``，供提示信息复用。"""
    return f"{rule.code} [{rule.level.value}] {rule.summary}"
