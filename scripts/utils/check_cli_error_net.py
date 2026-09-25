"""验证 CLI 的兜底异常处理确实生效。

**为什么需要这个检查**：兜底代码写在那里不等于会被调用——
入口点原先指向 `inloop.cli:app`，那样 `_run()` 永远不会执行。
因此这里必须真的**通过已安装的入口点**跑一次，并断言：

1. stdout 上仍是一份合法 JSON（调用方靠它判断失败原因）
2. 错误码是 `internal_error`
3. 退出码非 0
4. 提示里说明"这是工具缺陷，请反馈"

做法是临时造一个必然触发未预期异常的入口：调用 `app()` 时传入一个
会让内部代码抛非预期异常的输入。这里选用"`--content` 指向一个
权限不可读的目录"这类环境相关场景难以稳定复现，因此改为**直接注入**：
用一个测试专用的子进程脚本调用 `_run`，并让 `app` 抛异常。
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
PYTHON = REPO_ROOT / ".venv" / "Scripts" / "python.exe"

#: 在子进程里替换 app，让它抛一个未预期异常，然后走真实的 _run 兜底
INJECT = """
import sys
sys.argv = ["inloop", "--json", "list"]
import inloop.cli as cli

def boom(*args, **kwargs):
    raise RuntimeError("注入的测试异常")

cli.app = boom
cli._run()
"""


def main() -> int:
    print("验证 CLI 兜底异常处理")
    print()

    completed = subprocess.run(
        [str(PYTHON), "-c", INJECT],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=60,
        cwd=REPO_ROOT,
    )

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'✓' if ok else '✗'} {label}{f'　{detail}' if detail else ''}")
        failures += int(not ok)

    check("退出码非 0", completed.returncode != 0, f"exit={completed.returncode}")

    # 关键：stdout 必须是可解析的 JSON，而不是 traceback
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError as exc:
        payload = None
        check("stdout 是合法 JSON", False, f"{exc}；实际：{completed.stdout[:150]!r}")
    else:
        check("stdout 是合法 JSON", True)

    if payload is not None:
        check("ok 为 false", payload.get("ok") is False)
        error = payload.get("error", {})
        check(
            "错误码是 internal_error",
            error.get("code") == "internal_error",
            str(error.get("code")),
        )
        check(
            "message 含原始异常信息",
            "RuntimeError" in str(error.get("message", "")),
            str(error.get("message"))[:80],
        )
        check("提示说明这是缺陷并要反馈", "反馈" in str(error.get("hint", "")))

    # traceback 应当出现在 stderr（便于定位），而不是污染 stdout
    check("traceback 在 stderr 上", "Traceback" in completed.stderr)
    check("stdout 里没有 traceback", "Traceback" not in completed.stdout)

    print()
    print("✓ 全部通过" if not failures else f"✗ {failures} 项未通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
