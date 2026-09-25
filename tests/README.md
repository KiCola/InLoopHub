# tests —— 自动化测试

测试框架为 `pytest`，由 `pyproject.toml` 的 `[tool.pytest.ini_options]` 配置。
用 `python -m pytest` 运行（统一用 `python -m`，避免虚拟环境路径问题）。

## 布局

```text
tests/
├── fixtures/         测试用输入数据
└── test_*.py         测试用例
```

## 测试数据放哪里

- **能小则小。** 只为验证解析与渲染的最小样例放 `tests/fixtures/`，不要复制真实文章进来。
- **需要真实场景时用真实文章**，直接读 `articles/` 下的现有文章，而不是把文章再拷一份到 fixtures
  —— 两份副本必然漂移。任务书 §28 也明确要求用真实中文技术文章验证，而不是 lorem ipsum。
- 特意构造的错误样例（缺字段、坏路径、语法异常）放 `fixtures/`，命名要表明它坏在哪，例如
  `missing_cover_index.md`。

## 边界要求

按任务书 §22，测试至少要覆盖：Front Matter 解析、图片路径、Markdown 转 HTML、
inline CSS、代码块、表格、中文标题、Unicode、GIF、图片不存在、空字段。

**不许为了让测试变绿而放宽断言**（`AGENTS.md` §3）。测试挂了先找根因。
