"""入口薄封装：新建文章。

本文件只做转发，不实现逻辑 —— 真正的实现在 ``src/inloop/`` 内，
保证同一个功能只有一份代码（任务书复审已确认的方案）。

任务书 §3 规定了 ``scripts/`` 下的顶层脚本，它们的作用是：不安装也能直接运行。
为此这里做两件事：把 ``src/`` 加入模块搜索路径；若项目内存在 ``.venv`` 则改用它解释，
避免「依赖装在 venv、却用系统 Python 执行」导致 ImportError。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SRC = _REPO / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

# 项目内置虚拟环境存在时，把执行权交给它，保证依赖一致。
_VENV_PY = _REPO / ".venv" / "Scripts" / "python.exe"
if _VENV_PY.is_file() and Path(sys.executable).resolve() != _VENV_PY.resolve():
    os.execv(str(_VENV_PY), [str(_VENV_PY), str(Path(__file__).resolve()), *sys.argv[1:]])

from inloop.cli import app  # noqa: E402  (必须在调整 sys.path 之后导入)


def main() -> None:
    """以 ``new`` 子命令启动 CLI，保持参数解析完全一致。"""
    app(args=["new", *sys.argv[1:]])


if __name__ == "__main__":
    main()
