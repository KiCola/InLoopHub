"""解析层：Front Matter 与 Markdown。

职责边界（AGENTS.md §7）：

- ``frontmatter``：文本 → ``(meta, body)``，纯函数，不做语义校验。
- ``markdown``：Markdown → HTML 片段，不加样式、不改图片路径。

具体实现将在对应轮次接入。
"""
