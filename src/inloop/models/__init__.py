"""文章数据模型（Article Model）。

职责边界（AGENTS.md §7）：

- **负责**：front matter 的语义、字段校验规则、状态流转约束。
- **不负责**：读文件、解析 YAML、渲染 HTML。

具体实现将在 Front Matter Parser 就绪后接入，届时会补齐 Article 数据类
与 status / category 的枚举约束。
"""
