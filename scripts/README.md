# scripts —— CLI 入口薄封装

本目录下的脚本**只做转发**，不承载业务逻辑：

| 脚本 | 转发到 |
|---|---|
| `new_article.py` | `inloop new` |
| `check_article.py` | `inloop check` |
| `build_wechat.py` | `inloop build-wechat` |
| `generate_index.py` | `inloop index` |

## 为什么保留它们

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

上述四个命令**尚未实现**，因此直接运行这些脚本会得到 `No such command`。
这是预期行为——命令在各自模块完成后逐条接入，`AGENTS.md` §3 要求
未实现的入口不得伪装成可用。
