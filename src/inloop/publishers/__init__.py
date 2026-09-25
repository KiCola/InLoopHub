"""平台发布适配层。

只暴露抽象接口；具体平台实现在各自模块中，第一阶段仅 ``wechat``。
"""

from inloop.publishers.base import BuildArtifact, BuildResult, ImageRef, Publisher

__all__ = ["BuildArtifact", "BuildResult", "ImageRef", "Publisher"]
