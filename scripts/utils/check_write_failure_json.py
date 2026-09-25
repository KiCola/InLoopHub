"""确认在**无法写入**的情况下，`new` 仍给插件一份可解析的 JSON。

为什么专门测这个：会话沙箱不允许 Python 往 `C:` 盘 vault 写文件
（`WinError 5`），这恰好提供了一个真实的失败场景。我要确认的是——
**失败时 stdout 上仍是一份合法 JSON**，这样插件能显示"哪里错了、怎么改"，
而不是干瞪眼。

注意：这只验证"失败时的错误传递"，**不能**用来判断
"用户在真实 Obsidian 里新建文章会不会成功"——那是沙箱限制，
用户正常运行时不存在。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
EXECUTABLE = REPO_ROOT / ".venv" / "Scripts" / "inloop.exe"
#: 这个目录存在但当前会话写不进去（沙箱限制），正好当作失败场景
VAULT_CONTENT = Path(
    r"C:\Users\zzr\Nutstore\1\我的坚果云\obsidian\TechTree\InLoopPub"
)


def run(args: list[str]) -> tuple[int, dict | None, str, str]:
    completed = subprocess.run(
        [str(EXECUTABLE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**os.environ, "INLOOP_ROOT": str(REPO_ROOT)},
    )
    try:
        payload = json.loads(completed.stdout.strip())
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, completed.stdout, completed.stderr


def main() -> int:
    print("失败路径的错误传递（JSON 契约）")
    print(f"  内容目录：{VAULT_CONTENT}")
    print()

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'✓' if ok else '✗'} {label}{f'　{detail}' if detail else ''}")
        failures += int(not ok)

    code, payload, stdout, stderr = run(
        [
            "--json",
            "--content",
            str(VAULT_CONTENT),
            "new",
            "--title",
            "沙箱权限探针",
            "--slug",
            "sandbox-probe",
            "--category",
            "research",
            "--template",
            "research-note",
            "--tags",
            "探针",
            "--summary",
            "探针",
            "--yes",
        ]
    )

    # 无论成功还是失败，stdout 都必须是合法 JSON —— 这是插件的依赖
    check("stdout 是合法 JSON", payload is not None, repr(stdout[:120]))

    if payload is None:
        print()
        print("✗ 失败时没有给出 JSON，插件将无法显示有用的错误")
        return 1

    if payload.get("ok"):
        # 沙箱放宽时会走到这里（真的写成功了），那也算通过，但要清理
        check("新建成功（本会话沙箱允许写入）", True)
        year = VAULT_CONTENT / str(__import__("datetime").date.today().year)
        created = year / "001-sandbox-probe"
        if created.exists():
            cleanup_code, cleanup, _, _ = run(
                ["--json", "--content", str(VAULT_CONTENT), "delete", "sandbox-probe", "--yes"]
            )
            check("演练文章已清理", (cleanup or {}).get("removed") is True, f"exit={cleanup_code}")
    else:
        error = payload.get("error", {})
        check("ok 为 false", True)
        check("给出了错误码", bool(error.get("code")), str(error.get("code")))
        # 权限问题应当有**专门的**错误码，而不是混进 internal_error——
        # 后者提示"这是工具缺陷请反馈"，会把用户引向错误的方向。
        check(
            "错误码是 permission_denied（权限问题不该报成工具缺陷）",
            error.get("code") == "permission_denied",
            str(error.get("code")),
        )
        message = str(error.get("message", ""))
        check(
            "message 说明了真实原因",
            "Permission" in message or "拒绝访问" in message,
            message[:90],
        )
        hint = str(error.get("hint", ""))
        check("hint 给出权限的修正方向", "可写" in hint, hint[:70])
        check("hint 不再误导为工具缺陷", "工具自身的缺陷" not in hint)
        check("traceback 只在 stderr", "Traceback" in stderr and "Traceback" not in stdout)
        print()
        print("  说明：这里的失败源于本会话沙箱不允许写 C: 盘以外的 vault，")
        print("        不代表用户正常运行时也会失败。")

    print()
    print("✓ 全部通过" if not failures else f"✗ {failures} 项未通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
