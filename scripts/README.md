# scripts —— CLI 入口薄封装

本目录下的脚本**只做转发**，不承载业务逻辑：

| 脚本 | 转发到 |
|---|---|
| `new_article.py` | `inloop new` |
| `check_article.py` | `inloop check` |
| `build_wechat.py` | `inloop build-wechat` |
| `generate_index.py` | `inloop index` |

## activate.sh —— 激活虚拟环境（供 bash 系 shell）

```bash
source scripts/activate.sh
```

**必须用 `source`**（或 `.`），否则改动的 PATH 只作用于子进程，退出即失效——
这正是 `inloop: command not found` 最常见的原因。

虚拟环境自带的 `.venv/Scripts/activate` 本身没有问题，`source` 它同样有效。
本脚本的额外价值是**按当前平台习惯设置 PATH 并把结果报告出来**
（激活了哪个环境、版本号、可用的命令形式），省去"我到底激活成功没有"的猜测。

Windows 上 `python -m venv` 生成的是 `Scripts/inloop.exe`，Linux/macOS 生成的是
`bin/inloop`，本脚本会自动识别。

## utils/ —— 开发辅助脚本

`utils/` 下是**开发期**用的工具，不属于发布链路，也不发布给最终用户：

| 脚本 | 用途 |
|---|---|
| `verify_code_blocks.py` | 把产物里的代码块与源 Markdown **逐字符比对**。代码块的空白曾经在构建中丢失（词间空格粘连、缩进消失），而"看起来差不多"发现不了这种问题 |
| `check_doc_links.py` | 检查各文档里的**本地链接**是否指向真实存在的文件。排除代码块与行内代码里的示例链接 |
| `make_theme_preview.py` | 生成 `dist/theme-compare.html`，把各排版主题并排对比 |
| `make_sample_assets.py` | 生成示例文章用的示意图与封面占位图 |

`verify_code_blocks.py` 与 `check_doc_links.py` 是**验证工具**，
在改动渲染器或文档后应当跑一次；它们会以退出码 `0/1` 表示通过与否。

## 为什么保留入口脚本

任务书 §3 规定了这一结构，且它们有一个实际用处：**不安装也能直接运行**。
每个脚本会自己把 `src/` 加入模块搜索路径，因此无需先 `pip install -e .`。

## 虚拟环境处理

脚本启动时会检查项目内是否存在 `.venv`；若存在且当前解释器不是它，就把执行权
交给 `.venv` 的解释器。这样 `python scripts/xxx.py` 不会因为「依赖装在 venv、
却用系统 Python 跑」而报 ImportError。用 `python -m` 或直接调用 `inloop` 命令时不需要这层处理。

## 存放规则

- **禁止在这里写业务逻辑。** 同一个功能必须只有一份实现，放在 `src/inloop/` 内。
  脚本里出现第二份实现，就会出现「改了包、忘了脚本」的分叉。
- `utils/` 只放确实服务于脚本本身、且不适合被包复用的辅助代码；
  能被 `src/inloop/` 复用的逻辑放进包内。

## 当前状态

上表四个入口脚本均已接入，与 `inloop` 对应命令行为一致。
`utils/` 下的工具均已可用。
