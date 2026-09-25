# 路线图

依据任务书 §25、§26、§31。本文只记录**规划与其边界**，实际进度以轮次汇报为准。

## 第一阶段（P0）—— 让系统真的可用

任务书 §25 的 P0 十项，按任务书 §31 推荐的依赖顺序排列：

| # | 内容 | 状态 |
|---|---|---|
| 1 | 仓库初始化 | 完成 |
| 2 | Markdown 规范 | 完成：front matter 与正文格式均有校验与渲染实现 |
| 3 | Front Matter Parser | 完成 |
| 4 | Article Model | 完成（含序列化、规则码集中表） |
| 5 | `inloop new` | 完成（模板系统一并落地） |
| 6 | `inloop check` | 完成 |
| 7 | Markdown → HTML | 完成（含脚注、公式、任务列表的微信端降级） |
| 8 | 微信 inline CSS | 完成（样式来自 styles/*.css，产物零 class） |
| 9 | 图片处理 | 完成（格式/体积/绝对路径校验，结构化图片清单） |
| 10 | preview HTML | 完成（含 `inloop preview-wechat` 本地服务） |

**P0 已全部完成。** 超出 P0 清单但顺手完成的小项：`inloop status`（任务书 §17）、
`inloop rules`（规则码自查）、`inloop index`（任务书 §14）、pytest 测试套件。

## 第二阶段（P1）—— 让系统变得完整

任务书 §25 的 P1：README 索引、`metadata.json`、模板系统、Rich CLI、
GitHub Actions、pytest。

其中 README 索引、`metadata.json`、模板系统、pytest 已完成；**剩余 GitHub Actions**。

## 第三阶段（P2）—— 自动化

任务书 §25 的 P2：微信 API、自动上传图片、自动创建草稿、博客生成、
小红书卡片、B 站脚本、知乎适配。

其中前三项直接服务于本项目的终局目标（人只写 Markdown，程序完成发布），
见 `AGENTS.md` §11。当前架构已为它们预留接口与数据结构。

## 明确的边界

任务书 §26 划出的"不要做"清单：Docker、数据库、Web 后台、React/Vue 管理页面、
用户系统、OAuth、消息队列、微服务、Redis、Kubernetes。

第一阶段的全部技术栈就是：**Git + Markdown + Python CLI**。
这份清单的价值不在于限制想象力，而在于防止一个个人内容仓库被写成分布式系统。

## 不做什么决定

以下问题刻意留到第一篇真实文章跑通之后再回答（任务书 §31）：

- 是否修改目录结构
- 是否增加模板
- 是否调整样式系统
- 是否接入微信公众号 API
- 是否扩展到博客与其他平台

先让系统可用，再让它完整。
