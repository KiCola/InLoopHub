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
import re
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
    assert data["content_root"] == str(target.resolve()), (
        f"配置文件里的内容目录没有生效：得到 {data.get('content_root')}"
    )
    assert [a["dir_name"] for a in data["articles"]] == ["001-configured"]
