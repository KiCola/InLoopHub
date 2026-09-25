"""微信公众号平台适配。

本模块是 :class:`~inloop.publishers.base.Publisher` 的第一个实现，职责很薄：
把构建编排接到已冻结的接口上，使 ``build`` 与将来的 ``publish`` 共用一个入口。

``build`` 只产出本地文件，不需要网络与凭据；``publish`` / ``update`` 在平台
接口接入前保持显式失败，不用"假装成功"的返回值占位。
"""

from __future__ import annotations

from pathlib import Path

from inloop.build import BuildOutcome, build_article
from inloop.config import Config, load_config
from inloop.models.article import Article
from inloop.publishers.base import ArticleLike, BuildArtifact, BuildResult, ImageRef, Publisher


class WechatBuilder(Publisher):
    """微信公众号构建器。"""

    platform = "wechat"

    def __init__(self, config: Config | None = None) -> None:
        self._config = config

    @property
    def config(self) -> Config:
        """配置，首次访问时加载。"""
        if self._config is None:
            self._config = load_config()
        return self._config

    def build(self, article: ArticleLike) -> BuildResult:
        """构建文章产物。"""
        if not isinstance(article, Article):
            raise TypeError(
                f"WechatBuilder.build 需要 inloop.models.article.Article，"
                f"实际收到 {type(article).__name__}。"
            )

        outcome: BuildOutcome = build_article(article, config=self.config)
        return self._to_result(outcome)

    def _to_result(self, outcome: BuildOutcome) -> BuildResult:
        files = tuple(
            BuildArtifact(
                relative_path=relative,
                kind=_kind_of(relative),
                size_bytes=(outcome.output_dir / relative).stat().st_size,
            )
            for relative in outcome.files
        )
        # 图片清单必须同时保留「仓库内源路径」与「产物内路径」：
        # 将来逐张上传后要按产物路径回填正文，而上报给用户时用源路径更易定位。
        images = tuple(
            ImageRef(
                source_path=asset.source_path,
                output_path=asset.output_relative,
                html_src=asset.html_src,
                alt=asset.alt,
                from_markdown=asset.from_markdown,
            )
            for asset in outcome.images
        )
        return BuildResult(
            platform=self.platform,
            output_dir=outcome.output_dir,
            files=files,
            images=images,
            metadata=dict(outcome.metadata),
            warnings=tuple(outcome.warnings),
        )


def _kind_of(relative: Path) -> str:
    """按文件名判断产物用途。"""
    name = relative.name
    if name == "article.html":
        return "article-html"
    if name == "article.preview.html":
        return "preview-html"
    if name == "metadata.json":
        return "metadata"
    if relative.parent.name == "images":
        return "image"
    return "cover"
