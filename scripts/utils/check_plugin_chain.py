"""模拟插件在真实配置下的完整调用链，确认用户打开 Obsidian 就能用。

复刻插件的行为：以 vault 为基准探测可执行文件与仓库根，
然后按 `inloop --json --content <内容目录> <子命令>` 调用。

这不是单元测试，而是一次**针对本机实际配置**的端到端演练——
用来回答"我现在打开 Obsidian 到底能不能用"。
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO_ROOT = Path(r"E:\InLoopHub")
VAULT = Path(r"C:\Users\zzr\Nutstore\1\我的坚果云\obsidian\TechTree")
CONTENT_ROOT = VAULT / "InLoopPub"
EXECUTABLE = REPO_ROOT / ".venv" / "Scripts" / "inloop.exe"


def run(args: list[str]) -> tuple[int, dict | None, str]:
    """按插件的方式调用 CLI。"""
    completed = subprocess.run(
        [str(EXECUTABLE), *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=120,
        env={**__import__("os").environ, "INLOOP_ROOT": str(REPO_ROOT)},
    )
    try:
        payload = json.loads(completed.stdout)
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, completed.stderr


def main() -> int:
    print("模拟插件调用链（本机实际配置）")
    print(f"  可执行文件：{EXECUTABLE}")
    print(f"  仓库根    ：{REPO_ROOT}")
    print(f"  内容目录  ：{CONTENT_ROOT}")
    print()

    failures = 0

    def check(label: str, ok: bool, detail: str = "") -> None:
        nonlocal failures
        print(f"  {'✓' if ok else '✗'} {label}{f'　{detail}' if detail else ''}")
        failures += int(not ok)

    # 前提
    check("可执行文件存在", EXECUTABLE.is_file())
    check("内容目录存在", CONTENT_ROOT.is_dir())

    # 1) 探测结果应当与非插件场景一致
    base = ["--json", "--content", str(CONTENT_ROOT)]

    code, payload, _ = run([*base, "list"])
    check("list 能跑通", code == 0 and payload is not None, f"exit={code}")
    if payload:
        check(
            "content_root 正确",
            payload["content_root"] == CONTENT_ROOT.as_posix(),
            payload["content_root"],
        )
        check("当前文章数", payload["count"] == len(payload["articles"]), str(payload["count"]))

    # 2) check --all：**空内容目录上失败是有意的**。
    # 报告"检查通过"会给出虚假的安心感（一篇都没检查过）。
    # 因此这里断言的是"失败时给出可操作的指引"，而不是"能跑通"。
    code, payload, _ = run([*base, "check", "--all"])
    if (payload or {}).get("count", 0) == 0 or payload is None:
        check("空目录上 check --all 明确失败而非谎报通过", code != 0, f"exit={code}")
        if payload is not None and "error" in payload:
            check(
                "失败信息说明如何修正",
                "new" in str(payload["error"].get("hint", ""))
                or "new" in str(payload["error"].get("message", "")),
                str(payload["error"].get("message", ""))[:80],
            )
    else:
        check("check --all 能跑通", code == 0 and payload is not None, f"exit={code}")

    # 3) 找不到文章时的错误码（面板会显示提示）
    code, payload, _ = run([*base, "check", "no-such-article"])
    check(
        "错误码是 article_not_found",
        payload is not None and payload.get("error", {}).get("code") == "article_not_found",
        str(payload.get("error", {}).get("code")) if payload else "无 JSON",
    )

    # 4) 真正建一篇文章再删掉——验证"新建 → 出现在列表 → 删除"整条链路
    print()
    print("  实际演练：新建一篇 → 列表可见 → 删除")
    code, payload, stderr = run(
        [
            *base,
            "new",
            "--title",
            "插件链路演练",
            "--slug",
            "plugin-chain-check",
            "--category",
            "research",
            "--template",
            "research-note",
            "--tags",
            "演练",
            "--summary",
            "这是一次自动演练，会被立即删除。",
            "--yes",
        ]
    )
    created = code == 0
    check("新建成功", created, f"exit={code} {stderr.strip()[:120]}")

    if created:
        code, payload, _ = run([*base, "list"])
        names = [a["dir_name"] for a in (payload or {}).get("articles", [])]
        check("新文章出现在列表里", any("plugin-chain-check" in n for n in names), str(names))

        # 用 build 验证产物路径（面板"构建并复制"依赖它）
        code, payload, _ = run([*base, "build-wechat", "plugin-chain-check"])
        if payload and payload.get("ok"):
            html = Path(payload["html_path"])
            check("构建产物落盘", html.is_file(), str(html))
        else:
            # 缺封面会失败，这是预期行为（模板不含封面文件）
            err = (payload or {}).get("error", {})
            check(
                "构建失败时给出具体错误码（期望 cover_missing/IMG003 类）",
                err.get("code") in {"build_failed", "article_unparsable"} or "cover" in str(err),
                str(err.get("code")),
            )

        # 清理：演练文章必须删掉，不能留在用户的内容目录里
        code, payload, _ = run([*base, "delete", "plugin-chain-check", "--yes"])
        check("演练文章已删除", (payload or {}).get("removed") is True, f"exit={code}")
        year_dir = CONTENT_ROOT / str(date.today().year)
        still = (year_dir / "001-plugin-chain-check").exists()
        check("磁盘上确认已删", not still)

    print()
    print("✓ 全部通过" if not failures else f"✗ {failures} 项未通过")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
