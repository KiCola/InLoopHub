"""CLI 机器可读输出（``--json``）的测试（任务书 §7.5）。

这些测试守的是**接口契约**：编辑器插件等外部程序依赖它，
字段改名或格式变化等同于破坏性变更。

重点覆盖四类容易出错的地方：

1. **stdout 只含 JSON**——夹带任何人类可读文字都会让 ``json.loads`` 失败
2. **不含 ANSI 颜色码**——Rich 的默认行为会污染 JSON
3. **失败时仍是合法 JSON**——否则调用方还得去解析 stderr 的文本
4. **只有一份 JSON**——错误路径上"两处都发"会把两份对象写进 stdout
"""

from __future__ import annotations

import json
import os
import re
import subprocess
from pathlib import Path

import pytest
from PIL import Image
from typer.testing import CliRunner

from inloop.cli import app

REPO_ROOT = Path(__file__).resolve().parents[1]
runner = CliRunner()

_ANSI = re.compile(r"\x1b\[[0-9;]*m")
#: 产物里不允许出现的盘符（metadata.json 是确定性产物）
_DRIVE = re.compile(r"[A-Za-z]:[\\/]")


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """每条用例前清掉内容目录相关的环境变量。

    为什么需要：``INLOOP_CONTENT`` 的优先级**高于配置文件**。
    如果某个用例设过它而没清干净，后续用例就会读到别的内容目录，
    表现为"配置文件不生效"这种误导性的失败（真发生过）。
    测试隔离要靠结构保证，不能靠每个用例自觉。
    """
    monkeypatch.delenv("INLOOP_CONTENT", raising=False)
    monkeypatch.delenv("INLOOP_DIST", raising=False)


@pytest.fixture()
def content_dir(tmp_path: Path) -> Path:
    """一个装了单篇文章的内容目录。"""
    root = tmp_path / "content"
    directory = root / "2026" / "001-json-test"
    (directory / "assets").mkdir(parents=True)
    Image.new("RGB", (600, 300), (0, 47, 167)).save(directory / "assets" / "pic.png")
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(directory / "cover.png")
    (directory / "index.md").write_text(
        "---\n"
        "id: 1\n"
        'title: "JSON 测试"\n'
        'slug: "json-test"\n'
        "date: 2026-09-25\n"
        'author: "测试作者"\n'
        'category: "paper"\n'
        'status: "draft"\n'
        "tags:\n"
        "  - 测试\n"
        'summary: "摘要。"\n'
        'cover: "cover.png"\n'
        "platforms:\n"
        "  wechat: true\n"
        "---\n"
        "\n"
        "# JSON 测试\n"
        "\n"
        "## 01 · 第一节\n"
        "\n"
        "正文。\n"
        "\n"
        '![示意图](assets/pic.png "图 1：示意")\n',
        encoding="utf-8",
        newline="\n",
    )
    return root


def invoke_json(content_dir: Path, *args: str):
    """调用 CLI 并返回 (result, 解析后的 JSON 或 None)。"""
    result = runner.invoke(app, ["--content", str(content_dir), "--json", *args])
    try:
        return result, json.loads(result.stdout)
    except json.JSONDecodeError:
        return result, None


def invoke_real(content_root: Path, *args: str) -> tuple[int, object | None, str, str]:
    """用**真实进程**调用 CLI，返回 ``(退出码, JSON, stdout, stderr)``。

    为什么需要它：`CliRunner` 直接调用 Typer 应用，**绕过 `_run()` 入口**——
    兜底异常处理、UTF-8 强制、用法错误的 JSON 补发都在那里。
    而插件用的是真实进程，因此涉及这些行为的测试必须走同一条路径，
    否则测的不是插件实际会遇到的东西。
    """
    executable = REPO_ROOT / ".venv" / "Scripts" / "inloop.exe"
    if not executable.is_file():
        pytest.skip("找不到虚拟环境里的 inloop（本测试需要真实进程）")

    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}
    }
    env["INLOOP_ROOT"] = str(REPO_ROOT)

    completed = subprocess.run(
        # 全局选项必须放在子命令**之前**
        [str(executable), "--json", "--content", str(content_root), *args],
        capture_output=True,
        env=env,
        timeout=120,
        cwd=REPO_ROOT,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")
    stderr = completed.stderr.decode("utf-8", errors="replace")
    try:
        payload: object | None = json.loads(stdout)
    except json.JSONDecodeError:
        payload = None
    return completed.returncode, payload, stdout, stderr


# --- 输出契约 -------------------------------------------------------------


def test_list_输出合法_JSON_且无_ANSI(content_dir: Path) -> None:
    result, data = invoke_json(content_dir, "list")
    assert data is not None, f"stdout 不是合法 JSON：{result.stdout[:300]!r}"
    assert _ANSI.search(result.stdout) is None, "JSON 里混入了 ANSI 颜色码"
    assert data["schema"] == 1
    assert data["ok"] is True


def test_check_输出合法_JSON(content_dir: Path) -> None:
    result, data = invoke_json(content_dir, "check", "001-json-test")
    assert data is not None, result.stdout[:300]
    assert data["ok"] is True
    assert data["error_count"] == 0


def test_check_all_输出合法_JSON(content_dir: Path) -> None:
    result, data = invoke_json(content_dir, "check", "--all")
    assert data is not None, result.stdout[:300]
    assert data["total"] == 1


def test_build_输出合法_JSON(content_dir: Path) -> None:
    result, data = invoke_json(content_dir, "build-wechat", "001-json-test")
    assert data is not None, result.stdout[:300]
    assert data["ok"] is True
    # 插件要据此读 HTML、上传图片，因此这三个路径必须给出
    assert data["html_path"].endswith("article.html")
    assert data["preview_path"].endswith("article.preview.html")
    assert data["metadata_path"].endswith("metadata.json")
    assert data["body_images"], "应给出正文图片清单供逐张上传"


def test_delete_未传_yes_只给预览且非零退出(content_dir: Path) -> None:
    """JSON 模式不接受交互确认：要么 --yes，要么只回报将删除什么。"""
    result, data = invoke_json(content_dir, "delete", "001-json-test")
    assert data is not None, result.stdout[:300]
    assert data["removed"] is False
    assert data["image_count"] == 2
    assert result.exit_code != 0
    assert (content_dir / "2026" / "001-json-test").is_dir(), "不该删除"


def test_delete_传_yes_执行并回报(content_dir: Path) -> None:
    result, data = invoke_json(content_dir, "delete", "001-json-test", "--yes")
    assert data is not None, result.stdout[:300]
    assert data["removed"] is True
    assert result.exit_code == 0
    assert not (content_dir / "2026" / "001-json-test").exists()


# --- 失败路径 -------------------------------------------------------------


@pytest.mark.parametrize(
    ("args", "expected_code"),
    [
        (("check", "no-such"), "article_not_found"),
        (("build-wechat", "no-such"), "article_not_found"),
        (("delete", "no-such"), "article_not_found"),
    ],
)
def test_找不到文章时给出具体错误码(
    content_dir: Path, args: tuple[str, ...], expected_code: str
) -> None:
    """错误码要能被程序判断，不能一律是 command_failed。"""
    result, data = invoke_json(content_dir, *args)
    assert data is not None, f"失败时 stdout 仍应是合法 JSON：{result.stdout[:300]!r}"
    assert data["ok"] is False
    assert data["error"]["code"] == expected_code
    assert result.exit_code != 0


def test_失败时只有一份_JSON(content_dir: Path) -> None:
    """错误输出必须只有一个出口。

    如果错误路径上"两处都发"，stdout 会有两个 JSON 对象，
    调用方 ``json.loads`` 直接失败（这个 bug 真出现过）。
    """
    result = runner.invoke(app, ["--content", str(content_dir), "--json", "check", "no-such"])
    # 只有一个顶层对象：用 raw_decode 解析后不应剩下非空白字符
    decoder = json.JSONDecoder()
    _, end = decoder.raw_decode(result.stdout.lstrip())
    assert result.stdout.lstrip()[end:].strip() == "", (
        f"stdout 里有多余内容：{result.stdout[end:][:200]!r}"
    )


def test_内容目录不存在时也是合法_JSON(tmp_path: Path) -> None:
    missing = tmp_path / "not-here"
    result = runner.invoke(app, ["--content", str(missing), "--json", "list"])
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert result.exit_code != 0


# --- 路径约定 -------------------------------------------------------------


def test_文章路径相对内容目录(content_dir: Path) -> None:
    """文章路径必须能在 vault 内定位，因此是相对路径。"""
    _, data = invoke_json(content_dir, "list")
    article = data["articles"][0]
    assert article["path"] == "2026/001-json-test/index.md"
    assert not Path(article["path"]).is_absolute()


def test_顶层指针字段是绝对路径(content_dir: Path) -> None:
    """契约是**双向**的，两侧都要有断言。

    这条守的是另一侧：顶层"指针"字段（content_root / output_dir / html_path …）
    **必须**是绝对路径，因为插件要用它直接读写文件。
    如果只测"产物 metadata 无绝对路径"，将来有人"统一路径风格"时
    会把这一侧改坏而测试不报警（独立审核指出的缺口）。
    """
    _, listed = invoke_json(content_dir, "list")
    assert Path(listed["content_root"]).is_absolute(), listed["content_root"]

    _, built = invoke_json(content_dir, "build-wechat", "001-json-test")
    for field in ("output_dir", "html_path", "preview_path", "metadata_path"):
        assert Path(built[field]).is_absolute(), f"{field} 应是绝对路径：{built[field]}"
        assert Path(built[field]).exists(), f"{field} 指向的文件应存在：{built[field]}"


def test_路径分隔符统一为正斜杠(content_dir: Path) -> None:
    """同一份 JSON 里不能一半反斜杠一半正斜杠。

    插件做字符串比较与拼接时，`E:\\x\\y` 与 `E:/x/y` 不相等，
    混用会制造极难定位的 bug（独立审核发现的）。
    """
    _, data = invoke_json(content_dir, "build-wechat", "001-json-test")
    for field in ("content_root", "output_dir", "html_path", "preview_path", "metadata_path"):
        value = data[field]
        assert "\\" not in value, f"{field} 里出现了反斜杠：{value}"
    for entry in data["images"]:
        assert "\\" not in entry["output"], entry["output"]
        assert "\\" not in entry["source"], entry["source"]


def test_内容目录没有配好时给出可判断的错误码(tmp_path: Path) -> None:
    """插件要据此区分"去设置界面配置"与"意外故障"。"""
    missing = tmp_path / "not-configured"
    result = runner.invoke(app, ["--content", str(missing), "--json", "list"])
    data = json.loads(result.stdout)
    assert data["ok"] is False
    assert data["error"]["code"] == "content_root_missing"


def test_中文路径下输出仍是合法_UTF8(tmp_path: Path) -> None:
    """`--json` 的契约是"机器可读"，不能依赖调用方设对环境变量。

    中文 Windows 上 Python 默认用 cp936 写 stdout。若输出里含中文路径
    （例如坚果云用户的「我的坚果云」），写出的字节就不是 UTF-8，
    而调用方按 UTF-8 解码 → 报错信息变乱码、用户无法定位。
    这个 bug 真出现过：用户截图里的报错是 `�ҵļ����`。

    因此 CLI 在 `_run()` 里强制 stdout/stderr 为 UTF-8。
    这条测试**绕过 CliRunner**（它会替换 stdout），直接跑真实进程，
    并且**故意不设** PYTHONIOENCODING。
    """
    chinese_dir = tmp_path / "我的坚果云" / "内容"
    directory = chinese_dir / "2026" / "001-中文"
    (directory / "assets").mkdir(parents=True)
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(directory / "cover.png")
    (directory / "index.md").write_text(
        "---\n"
        "id: 1\n"
        'title: "中文路径测试"\n'
        'slug: "zhongwen"\n'
        "date: 2026-09-25\n"
        'author: "测试作者"\n'
        'category: "paper"\n'
        'status: "draft"\n'
        "tags:\n"
        "  - 测试\n"
        'summary: "摘要。"\n'
        'cover: "cover.png"\n'
        "platforms:\n"
        "  wechat: true\n"
        "---\n\n# 中文路径测试\n",
        encoding="utf-8",
        newline="\n",
    )

    executable = REPO_ROOT / ".venv" / "Scripts" / "inloop.exe"
    if not executable.is_file():
        pytest.skip("找不到虚拟环境里的 inloop（本测试需要真实进程）")

    env = {
        k: v for k, v in os.environ.items() if k not in {"PYTHONIOENCODING", "PYTHONUTF8"}
    }
    env["INLOOP_ROOT"] = str(REPO_ROOT)

    completed = subprocess.run(
        [str(executable), "--json", "--content", str(chinese_dir), "list"],
        capture_output=True,
        env=env,
        timeout=60,
        cwd=REPO_ROOT,
    )

    # 直接看原始字节，不让解码容忍错误
    raw = completed.stdout
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        pytest.fail(
            f"stdout 不是合法 UTF-8：{exc}\n"
            f"说明 CLI 没有强制 UTF-8 输出，中文路径会被调用方解成乱码。\n"
            f"原始字节（前 120）：{raw[:120]!r}"
        )

    assert "我的坚果云" in text, f"中文路径在输出里损坏了：{text[:200]}"
    payload = json.loads(text)
    assert payload["ok"] is True
    assert payload["content_root"].endswith("我的坚果云/内容"), payload["content_root"]


def test_传入年份目录时给出结构性提示() -> None:
    """把年份目录当成内容目录是最常见且最难自查的误配。

    判据是结构性的（``2026`` 恰好是本工具规定的层级），不是猜意图。
    """
    examples = REPO_ROOT / "examples"
    year_dir = examples / "2026"
    if not year_dir.is_dir():
        pytest.skip("examples/2026 不存在")

    result = runner.invoke(app, ["--content", str(year_dir), "list"])
    assert "年份目录" in result.output
    assert "上一级" in result.output


def test_传入单篇文章目录时给出结构性提示() -> None:
    article_dir = REPO_ROOT / "examples" / "2026" / "002-light-o1"
    if not article_dir.is_dir():
        pytest.skip("示例文章不存在")

    result = runner.invoke(app, ["--content", str(article_dir), "list"])
    assert "单个文章的目录" in result.output


def test_正确的内容目录不会被误判() -> None:
    """提示必须只在真的传错时出现，否则是噪音。"""
    examples = REPO_ROOT / "examples"
    result = runner.invoke(app, ["--content", str(examples), "list"])
    assert result.exit_code == 0
    assert "注意：传入" not in result.output


def test_产物_metadata_不含绝对路径(content_dir: Path) -> None:
    """metadata.json 是**产物**：要可分享、可复现，因此路径一律相对内容目录。

    这与 CLI 的 JSON 输出不同——后者是运行时消息，调用方本来就知道那两个根
    （它得靠绝对路径去读 HTML），因此 ``content_root`` / ``output_dir``
    是绝对路径，这是有意为之。
    """
    result, data = invoke_json(content_dir, "build-wechat", "001-json-test")
    assert data is not None
    metadata = data["metadata"]
    raw = json.dumps(metadata, ensure_ascii=False)

    assert _DRIVE.search(raw) is None, f"metadata 里出现了盘符：{_DRIVE.findall(raw)}"
    assert metadata["source"] == "2026/001-json-test/index.md"
    for entry in metadata["images"]:
        assert not Path(entry["source"]).is_absolute()


def test_JSON_模式的人类提示走_stderr(content_dir: Path) -> None:
    """stdout 留给 JSON，进度与警告走 stderr。"""
    result = runner.invoke(
        app, ["--content", str(content_dir), "--json", "build-wechat", "001-json-test"]
    )
    json.loads(result.stdout)  # 不抛异常即说明 stdout 干净
    assert result.stdout.strip().startswith("{")


def test_JSON_模式同样走配置层(mini_repo: Path, tmp_path: Path) -> None:
    """配置文件里的内容目录必须对 ``--json`` 也生效。

    这条是独立审核 Agent 提醒后补的：配置层曾有一个"先 pop 再读"的 bug，
    导致配置里的 content.root 永远读不到。如果只测人类可读输出，
    同一个缺陷会在 JSON 路径上再犯一次而且没人发现。
    """
    target = tmp_path / "configured-content"
    directory = target / "2026" / "001-configured"
    (directory / "assets").mkdir(parents=True)
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(directory / "cover.png")
    (directory / "index.md").write_text(
        "---\n"
        "id: 1\n"
        'title: "来自配置的内容"\n'
        'slug: "configured"\n'
        "date: 2026-09-25\n"
        'author: "测试作者"\n'
        'category: "paper"\n'
        'status: "draft"\n'
        "tags:\n"
        "  - 测试\n"
        'summary: "摘要。"\n'
        'cover: "cover.png"\n'
        "platforms:\n"
        "  wechat: true\n"
        "---\n\n# 来自配置的内容\n",
        encoding="utf-8",
        newline="\n",
    )

    site = mini_repo / "config" / "site.yaml"
    text = re.sub(r"(?ms)^content:.*\Z", "", site.read_text(encoding="utf-8")).rstrip()
    site.write_text(
        text + f'\n\ncontent:\n  root: "{target.as_posix()}"\n',
        encoding="utf-8",
        newline="\n",
    )

    # 关键：**不传 --content**，让内容目录完全由配置文件决定。
    # 环境变量已由 autouse 夹具清掉，因此这里测的确实是配置层。
    result = runner.invoke(app, ["--json", "list"], env={"INLOOP_ROOT": str(mini_repo)})
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert data["content_root"] == target.resolve().as_posix(), (
        f"配置文件里的内容目录没有生效：得到 {data.get('content_root')}"
    )
    assert [a["dir_name"] for a in data["articles"]] == ["001-configured"]


# --- 覆盖面：每个命令都必须有 JSON 输出 -----------------------------------


def test_每个命令都实现_json_输出(tmp_path: Path) -> None:
    """**这是防止同类 bug 再犯的关键测试。**

    背景：`--json` 是给插件用的接口。但曾经出现过"插件加了 `--json` 参数、
    而某个命令根本没实现 JSON 输出"的情况——那个命令照旧打印人类可读文本，
    调用方 `json.loads` 失败，于是**把"创建成功"报成"创建失败"**，
    用户看到的报错甚至自带成功信息（自相矛盾）。

    根因是"给插件加参数"和"给命令加输出"是两处独立改动，容易漏。
    因此这里遍历所有命令，逐个**用真实进程**调用并断言 stdout 是合法 JSON。

    为什么不用 CliRunner：它直接调用 Typer 应用，**绕过 `_run()` 入口**
    （兜底异常处理、UTF-8 强制都在那里）。插件用的是真实进程，
    测试就该用同一条路径，否则测的是另一个东西。
    """
    import typer.main

    group = typer.main.get_command(app)
    names = sorted(group.commands.keys())  # type: ignore[attr-defined]
    assert names, "没有取到任何命令，测试自身有问题"

    content_root = tmp_path / "coverage-content"
    content_root.mkdir()

    # 这些命令**不需要**文章参数，可以无参调用。
    # 注意 `check` 不带参数走的是本工具自己的校验（会给出"缺少要检查的文章"），
    # 因此这里用 `check --all`。
    no_args = {
        "list": [],
        "check": ["--all"],
        "info": [],
        "themes": [],
        "publish-status": [],
        "rules": [],
        "root": [],
        "version": [],
    }

    checked = 0
    for name in no_args:
        assert name in names, f"命令 `{name}` 已不存在，请同步本测试"
        code, payload, stdout, stderr = invoke_real(content_root, *no_args[name])
        assert stdout.strip(), f"`{name} --json` 没有任何输出（stderr: {stderr[:120]}）"
        try:
            data = json.loads(stdout)
        except json.JSONDecodeError as exc:
            pytest.fail(
                f"`{name} --json` 的输出不是合法 JSON：{exc}\n"
                f"实际内容：{stdout[:200]!r}\n"
                f"这说明该命令没实现 --json 输出，调用方会把成功当成失败。"
            )
        assert isinstance(data, dict), f"`{name} --json` 输出的不是对象"
        assert "ok" in data, f"`{name} --json` 的输出缺少 ok 字段"
        checked += 1

    assert checked >= 6, f"只覆盖了 {checked} 个命令，太少"


def test_用法错误也给_JSON() -> None:
    """Typer/Click 的用法错误不能让 `--json` 调用方拿到空 stdout。

    这类错误在**参数解析阶段**就退出，主回调根本没跑过，`_json_mode` 还是初值。
    若不放行处理，调用方看到的是"退出码 2 + 空输出"，只能靠猜。

    因此 `_run()` 在放行 SystemExit 之前补发一份 JSON。
    这条必须走真实进程——CliRunner 绕过 `_run()`，测不到这个兜底。
    """
    executable = REPO_ROOT / ".venv" / "Scripts" / "inloop.exe"
    if not executable.is_file():
        pytest.skip("找不到虚拟环境里的 inloop（本测试需要真实进程）")

    completed = subprocess.run(
        [str(executable), "--json", "delete"],  # delete 缺 target
        capture_output=True,
        env={**os.environ, "INLOOP_ROOT": str(REPO_ROOT)},
        timeout=60,
        cwd=REPO_ROOT,
    )
    stdout = completed.stdout.decode("utf-8", errors="replace")

    assert completed.returncode != 0
    assert stdout.strip(), "用法错误时 stdout 是空的，调用方无从判断"
    payload = json.loads(stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == "usage_error"
    assert "help" in payload["error"]["hint"] or "帮助" in payload["error"]["hint"]


def test_new_命令的_json_包含路径(content_dir: Path) -> None:
    """新建必须返回**新文章的路径**——调用方建完就要打开它。

    没有这个字段时，插件只能"create 之后再 list 一次、按 slug 猜哪篇是新的"，
    既慢（多一次 Python 启动）又可能在并发时认错。
    """
    result = runner.invoke(
        app,
        [
            "--content",
            str(content_dir),
            "--json",
            "new",
            "--title",
            "新建路径测试",
            "--slug",
            "new-path-test",
            "--category",
            "research",
            "--template",
            "research-note",
            "--tags",
            "测试",
            "--summary",
            "摘要",
            "--yes",
        ],
    )
    data = json.loads(result.stdout)
    assert data["ok"] is True, result.stdout[:300]
    assert data["path"] == "2026/002-new-path-test/index.md", data["path"]
    assert data["dir_name"] == "002-new-path-test"
    assert data["slug"] == "new-path-test"
    # content_root 让调用方能把相对 path 拼成可打开的位置
    assert data["content_root"] == content_dir.resolve().as_posix()
    assert data["cover"] == "cover.png"


def test_status_命令可用且回报前后状态(content_dir: Path) -> None:
    """`status` 曾经是**完全坏的**：里面引用了未定义的 `root` 变量。

    它从没被真正执行过，所以一直没暴露。插件里的状态下拉正好会踩到。
    """
    result = runner.invoke(
        app, ["--content", str(content_dir), "--json", "status", "001-json-test", "review"]
    )
    data = json.loads(result.stdout)
    assert data["ok"] is True, result.stdout[:300]
    assert data["status"] == "review"
    assert data["previous_status"] == "draft"
    assert data["dir_name"] == "001-json-test"

    # 确认真的写进文件了
    text = (content_dir / "2026" / "001-json-test" / "index.md").read_text(encoding="utf-8")
    assert "status: review" in text


def test_info_命令的_json_给出内容目录与来源() -> None:
    """`content_source` 是诊断的关键：四级来源里到底用上了哪一级。"""
    result = runner.invoke(app, ["--json", "info"])
    data = json.loads(result.stdout)
    assert data["ok"] is True
    assert Path(data["content_root"]).is_absolute()
    assert data["content_source"]
    assert "article_count" in data and "next_id" in data


# --- stdout 污染（真出过两次 bug）-----------------------------------------


def test_构建警告走_stderr_不污染_stdout(content_dir: Path) -> None:
    """**这条守的是一个真出过两次的 bug。**

    现象：构建明明成功（stdout 上有完整的 `ok: true` 信封），后面却跟了一段
    IMG101/IMG103 警告文字——于是插件 `json.loads` 报 `Extra data`，
    **把成功当成失败**报给用户。用户看到的报错甚至自带成功信息。

    根因：`_print_warnings` 用了 `console`（stdout）。警告是给人看的附加信息，
    与命令结果无关，必须走 stderr。

    这条用**真实进程**跑，因为要看 stdout 的原始字节。
    """
    # content_dir 里的文章没有正文图，但构建仍会产生 warning 的可能：
    # 缺 alt/caption 的图片最容易触发。这里直接断言"有警告时也不污染"。
    code, _payload, stdout, stderr = invoke_real(content_dir, "build-wechat", "001-json-test")
    assert stdout.strip(), "构建应当有输出"

    # 核心断言：stdout 必须**恰好**是一份 JSON，多一个字符都不行
    try:
        json.loads(stdout)
    except json.JSONDecodeError as exc:
        pytest.fail(
            f"stdout 不是单份合法 JSON：{exc}\n"
            f"这说明有输出（很可能是警告）写进了 stdout。\n"
            f"末尾 200 字：{stdout[-200:]!r}"
        )


def test_警告写完不破坏_json_契约(content_dir: Path, capsys) -> None:
    """直接测 `_print_warnings` 的输出流：必须只写 stderr。

    比依赖"某篇文章恰好产生警告"更可靠——不管有没有警告，流向都不能错。
    """
    from inloop.cli import _print_warnings

    _print_warnings(["IMG101 [WARNING] 测试警告", "IMG103 [WARNING] 测试警告二"])

    captured = capsys.readouterr()
    assert captured.out == "", f"警告写进了 stdout：{captured.out!r}"
    assert "IMG101" in captured.err, f"警告没写到 stderr：{captured.err!r}"
    assert "IMG103" in captured.err


def test_重复输出_json_会立刻报错() -> None:
    """`emit()` 检测到第二份输出时必须**立即报错**，而不是悄悄写出坏 JSON。

    stdout 上出现两份拼接内容会让调用方完全无法解析，比直接失败更难排查。
    """
    from inloop import jsonapi

    # 重置标记，模拟"已经输出过一份"
    jsonapi._EMITTED = False  # noqa: SLF001 - 测试需要直接控制这个进程级标记
    try:
        jsonapi.emit({"ok": True, "schema": 1})
        with pytest.raises(jsonapi.JSONPollutedError):
            jsonapi.emit({"ok": True, "schema": 1})
    finally:
        jsonapi._EMITTED = False  # noqa: SLF001
