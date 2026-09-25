# docs —— 开发文档

> **"怎么用"写在 [README](../README.md#怎么用) 里**，不在本目录重复。

| 文件 | 内容 |
|---|---|
| `getting-started.md` | 上手补遗：首次配置、命令执行位置、建议的写作节奏（完整用法见 README） |
| `architecture.md` | Article Model、Parser、Renderer、Wechat Adapter、Asset Pipeline、发布接口的架构说明（任务书 §29 指定必须解释这六项） |
| `content-workflow.md` | 从 idea 到 published 的内容工作流（任务书 §17） |
| `publishing-guide.md` | 构建产物如何复制进微信公众号后台的逐步操作（任务书 §18） |
| `style-guide.md` | 写作层面的规范：标题写法、术语、图片规格、三种引用形态 |
| `roadmap.md` | 第一/二/三阶段规划与当前落点 |

## 文档编写规则

- **不重复任务书。** 任务书是需求的事实源；本目录只写「怎么实现的、为什么这样实现」，
  以及任务书里没有交待的操作细节。重复抄一遍需求，两边一定会不一致。
- **写实现依据，不写宣传话术。** 说清某个设计解决了什么具体问题，比形容词有用。
- **改代码时同步改文档。** 尤其 `architecture.md`，它是新读者理解代码的第一入口。
