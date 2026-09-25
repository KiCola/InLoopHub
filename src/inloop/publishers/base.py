"""平台发布适配层的统一抽象。

设计依据：任务书 §19、AGENTS.md §11 第 3 条。

三条必须在接口层面守住的性质：

1. **与内容源解耦。** 本层只依赖文章数据模型，不读 Markdown、不解析 front matter、
   不关心仓库目录结构。
2. **构建与发布分离。** ``build`` 产出可交付的构建结果（本地文件），可在无网络、
   无凭据的情况下完成；``publish`` 才涉及平台账号与网络。第一阶段的半自动流程
   只用到 ``build``。
3. **可重写引用。** 构建结果里必须保留「图片相对路径 → 平台地址」的对应关系，
   使将来的 ``publish`` 能逐张上传后回填正文，而无需反向解析 HTML
   （AGENTS.md §11 第 2 条）。

新增平台时只允许新增本层的实现，不得改动文章模型、front matter 字段或既有命令语义。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

# --- 数据结构 -------------------------------------------------------------


@dataclass(frozen=True)
class BuildArtifact:
    """一次构建产出的单个文件。"""

    #: 文件路径，相对于 :attr:`BuildResult.output_dir`
    relative_path: Path
    #: 该文件的用途，例如 "article-html" / "preview-html" / "metadata" / "image" / "cover"
    kind: str
    #: 文件字节数，便于上层汇总与体积检查
    size_bytes: int


@dataclass(frozen=True)
class ImageRef:
    """正文中被引用的图片，供将来上传后回填路径。

    Attributes:
        source_path: 仓库内的原始图片路径（相对仓库根）。
        output_path: 构建产物中的图片路径（相对 :attr:`BuildResult.output_dir`）。
        html_src: 构建产物正文 HTML 中使用的 ``src`` 值，即需要被替换的字符串。
        alt: 图片替代文字。
        from_markdown: 是否来自正文 Markdown（True）还是封面等元数据（False）。
    """

    source_path: Path
    output_path: Path
    html_src: str
    alt: str
    from_markdown: bool = True


@dataclass(frozen=True)
class BuildResult:
    """一次构建的完整结果。

    Attributes:
        platform: 平台标识，例如 ``"wechat"``。
        output_dir: 产物根目录。
        files: 产物文件清单。
        images: 正文引用的图片清单，供发布阶段上传与回填。
        metadata: 平台发布所需的元数据字典（标题、摘要、封面等）。
        warnings: 构建过程中的非致命问题，需在 CLI 中原样展示给用户。
    """

    platform: str
    output_dir: Path
    files: tuple[BuildArtifact, ...]
    images: tuple[ImageRef, ...]
    metadata: dict[str, Any]
    warnings: tuple[str, ...] = ()


@runtime_checkable
class ArticleLike(Protocol):
    """``Publisher`` 对文章对象的最小要求。

    这里刻意用 Protocol 而不是直接 import 具体的 Article 类，
    使本层不依赖 ``inloop.models`` 的实现细节，便于替换与测试。
    """

    #: 文章标题
    title: str
    #: 文章唯一标识（目录名，形如 ``002-light-o1``）
    slug: str
    #: 文章正文 Markdown 源文本
    body: str


# --- 抽象基类 -------------------------------------------------------------


class Publisher(ABC):
    """平台发布适配层。

    子类必须实现 :meth:`build`；:meth:`publish` 与 :meth:`update` 在平台能力
    真正接入前保持显式失败，禁止用「假装成功」的返回值占位。
    """

    #: 平台标识，子类必须覆盖
    platform: str = ""

    @abstractmethod
    def build(self, article: ArticleLike) -> BuildResult:
        """把文章构建为该平台可消费的产物。"""
        ...

    def publish(self, article: ArticleLike) -> Any:
        """把文章发布到平台（第一阶段不实现）。

        Raises:
            NotImplementedError: 平台发布能力尚未接入。
        """
        raise NotImplementedError(
            f"平台 `{self.platform}` 的自动发布尚未实现。\n"
            f"当前阶段请使用构建功能生成产物，再按发布指南人工完成。"
        )

    def update(self, article: ArticleLike) -> Any:
        """更新平台上已发布的文章（第一阶段不实现）。

        Raises:
            NotImplementedError: 平台更新能力尚未接入。
        """
        raise NotImplementedError(
            f"平台 `{self.platform}` 的文章更新尚未实现。\n"
            f"当前阶段请重新构建产物后人工替换。"
        )
