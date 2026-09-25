"""解析层：Front Matter 与 Markdown。

职责边界（AGENTS.md §7）：

- ``frontmatter``：文本 → ``(meta, body)``，纯函数，不做语义校验。
- ``markdown``：Markdown → HTML 片段，不加样式、不改图片路径。

``markdown`` 将在 Markdown → HTML 渲染轮次接入。
"""

from inloop.parser.frontmatter import DELIMITER, FrontMatter, FrontMatterError, parse_front_matter

__all__ = ["DELIMITER", "FrontMatter", "FrontMatterError", "parse_front_matter"]
