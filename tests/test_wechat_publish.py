"""微信公众号发布链路的测试（任务书 §19、§25 第 18–19 项）。

## 这些测试能覆盖什么、不能覆盖什么

**能覆盖**：凭据读取与优先级、multipart 编码、错误码翻译、
正文图片的路径回填、以及整条"上传 → 回填 → 建草稿"的编排逻辑。
这些都通过注入 ``transport`` 假装 API 响应来完成，**不发真实网络请求**。

**不能覆盖**：真实的接口路径与参数是否正确。
本机没有公众号凭据、也没有固定 IP（家宽 IP 不稳定，加不了白名单），
因此 ``_API_*`` 常量里的地址从未被真实调用验证过。
首次在有凭据的环境里使用时必须核对一遍。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from PIL import Image

from inloop.publishers.wechat_api import (
    _API_ADD_DRAFT,
    _API_ADD_MATERIAL,
    _API_TOKEN,
    _API_UPLOAD_IMG,
    CREDENTIALS_FILE_NAME,
    WechatClient,
    WechatCredentials,
    WechatError,
    load_credentials,
)
from inloop.publishers.wechat_publish import (
    PUBLISHED_HTML_NAME,
    PublishNotConfigured,
    credentials_available,
    publish_article,
    rewrite_image_sources,
)


def make_client(handler) -> WechatClient:
    """造一个用假 transport 的客户端，避免真实网络调用。"""
    client = WechatClient(
        credentials=WechatCredentials("wx-test-appid", "test-secret", source="测试"),
        transport=handler,
    )
    return client


# --- 凭据 -----------------------------------------------------------------


def test_环境变量提供凭据(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("INLOOP_WECHAT_APPID", "wx-env")
    monkeypatch.setenv("INLOOP_WECHAT_SECRET", "env-secret")
    creds = load_credentials(tmp_path)
    assert creds is not None
    assert creds.appid == "wx-env"
    assert "环境变量" in creds.source


def test_凭据文件次之(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("INLOOP_WECHAT_APPID", raising=False)
    monkeypatch.delenv("INLOOP_WECHAT_SECRET", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / CREDENTIALS_FILE_NAME).write_text(
        json.dumps({"appid": "wx-file", "secret": "file-secret"}), encoding="utf-8"
    )
    creds = load_credentials(tmp_path)
    assert creds is not None
    assert creds.appid == "wx-file"


def test_没有凭据时返回_None_而不是报错(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """没配置是**正常状态**（半自动流程），不该当成错误。"""
    monkeypatch.delenv("INLOOP_WECHAT_APPID", raising=False)
    monkeypatch.delenv("INLOOP_WECHAT_SECRET", raising=False)
    assert load_credentials(tmp_path) is None
    assert credentials_available(tmp_path) is False


def test_凭据文件格式错误时给出可定位提示(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("INLOOP_WECHAT_APPID", raising=False)
    monkeypatch.delenv("INLOOP_WECHAT_SECRET", raising=False)
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / CREDENTIALS_FILE_NAME).write_text("{ 不是 JSON", encoding="utf-8")
    with pytest.raises(WechatError) as excinfo:
        load_credentials(tmp_path)
    assert excinfo.value.code == "credentials_invalid"
    assert CREDENTIALS_FILE_NAME in str(excinfo.value)


def test_凭据脱敏展示不泄漏完整_secret() -> None:
    creds = WechatCredentials("wx-a", "super-secret-value")
    masked = creds.masked()
    assert "super-secret-value" not in masked
    assert "wx-a" in masked


# --- token 与错误翻译 -----------------------------------------------------


def test_access_token_被缓存() -> None:
    """token 有效期 7200 秒，不该每次调用都重新取。"""
    calls: list[str] = []

    def handler(url, method, body, headers):
        calls.append(url)
        return json.dumps({"access_token": "tok-1", "expires_in": 7200})

    client = make_client(handler)
    assert client.access_token() == "tok-1"
    assert client.access_token() == "tok-1"
    assert len(calls) == 1, f"应当只取一次，实际 {len(calls)} 次"


@pytest.mark.parametrize(
    ("errcode", "expected_hint_fragment"),
    [
        (40001, "AppSecret"),
        (40164, "白名单"),
        (48001, "未授权"),
    ],
)
def test_已知错误码给出可操作的提示(errcode: int, expected_hint_fragment: str) -> None:
    """错误提示必须说清"怎么改"，而不是只报一个数字。"""

    def handler(url, method, body, headers):
        return json.dumps({"errcode": errcode, "errmsg": "some error"})

    client = make_client(handler)
    with pytest.raises(WechatError) as excinfo:
        client.access_token()
    assert excinfo.value.errcode == errcode
    assert expected_hint_fragment in excinfo.value.hint
    assert str(errcode) in str(excinfo.value)


def test_未知错误码保留原始编号便于查文档() -> None:
    def handler(url, method, body, headers):
        return json.dumps({"errcode": 99999, "errmsg": "unknown"})

    client = make_client(handler)
    with pytest.raises(WechatError) as excinfo:
        client.access_token()
    assert excinfo.value.errcode == 99999
    assert "99999" in str(excinfo.value)


# --- multipart 编码 -------------------------------------------------------


def test_上传图片使用_multipart_编码(tmp_path: Path) -> None:
    image = tmp_path / "pic.png"
    Image.new("RGB", (10, 10), (1, 2, 3)).save(image)

    captured: dict[str, object] = {}

    def handler(url, method, body, headers):
        if url.startswith(_API_TOKEN):
            return json.dumps({"access_token": "tok", "expires_in": 7200})
        captured["method"] = method
        captured["body"] = body
        captured["headers"] = headers
        captured["url"] = url
        return json.dumps({"url": "https://mmbiz.qpic.cn/xxx"})

    client = make_client(handler)
    result = client.upload_body_image(image)

    assert result == "https://mmbiz.qpic.cn/xxx"
    assert captured["method"] == "POST"
    content_type = str(captured["headers"].get("Content-Type", ""))
    assert content_type.startswith("multipart/form-data; boundary=")
    body = captured["body"]
    assert isinstance(body, bytes)
    assert b'name="media"' in body
    assert b"pic.png" in body
    # 二进制内容应原样进入请求体
    assert image.read_bytes() in body


def test_上传不存在的图片给出可定位错误(tmp_path: Path) -> None:
    client = make_client(lambda *a: json.dumps({"url": "x"}))
    with pytest.raises(WechatError) as excinfo:
        client.upload_body_image(tmp_path / "nope.png")
    assert excinfo.value.code == "image_not_found"


# --- 路径回填 -------------------------------------------------------------


def test_路径回填替换正文里的相对路径() -> None:
    html = '<p>x</p><img src="images/a.png"><img src="images/b.png">'
    mapping = {"images/a.png": "https://mmbiz/a", "images/b.png": "https://mmbiz/b"}
    rewritten, count = rewrite_image_sources(html, mapping)
    assert "images/a.png" not in rewritten
    assert "https://mmbiz/a" in rewritten
    assert "https://mmbiz/b" in rewritten
    assert count == 2


def test_路径回填不受映射顺序影响() -> None:
    """前缀重叠时（a.png 与 a.png.bak）不能误替换——这里验证精确子串替换。"""
    html = '<img src="images/a.png">'
    rewritten, count = rewrite_image_sources(html, {"images/a.png": "https://x"})
    assert rewritten == '<img src="https://x">'
    assert count == 1


def test_同一张图出现多次会全部替换() -> None:
    html = '<img src="images/a.png"><img src="images/a.png">'
    _, count = rewrite_image_sources(html, {"images/a.png": "https://x"})
    assert count == 2


# --- 整条编排 -------------------------------------------------------------


@pytest.fixture()
def built_article(tmp_path: Path) -> tuple[Path, dict, Path]:
    """造一份"已构建"的产物：正文 HTML + 图片 + metadata。"""
    output_dir = tmp_path / "dist" / "001-x"
    (output_dir / "images").mkdir(parents=True)
    Image.new("RGB", (60, 30), (0, 47, 167)).save(output_dir / "images" / "a.png")
    Image.new("RGB", (1175, 500), (0, 47, 167)).save(output_dir / "cover.png")

    html_path = output_dir / "article.html"
    html_path.write_text(
        '<html><body><p>正文</p><img src="images/a.png" alt="图"></body></html>',
        encoding="utf-8",
    )

    metadata = {
        "title": "测试文章",
        "author": "作者",
        "summary": "摘要",
        "images": [
            {
                "order": 1,
                "kind": "body",
                "output": "images/a.png",
                "source": "2026/001-x/assets/a.png",
                "byte_size": 100,
                "width": 60,
                "height": 30,
                "section": "第一节",
                "alt": "图",
                "caption": "",
            },
            {
                "order": 2,
                "kind": "cover",
                "output": "cover.png",
                "source": "2026/001-x/cover.png",
                "byte_size": 100,
                "width": 1175,
                "height": 500,
                "section": "",
                "alt": "封面",
                "caption": "",
            },
        ],
    }
    return output_dir, metadata, html_path


def test_完整发布流程会回填图片并建草稿(
    tmp_path: Path, built_article: tuple[Path, dict, Path]
) -> None:
    output_dir, metadata, html_path = built_article
    seen: list[str] = []

    def handler(url, method, body, headers):
        seen.append(url)
        if url.startswith(_API_TOKEN):
            return json.dumps({"access_token": "tok", "expires_in": 7200})
        if url.startswith(_API_UPLOAD_IMG):
            return json.dumps({"url": "https://mmbiz.qpic.cn/body"})
        if url.startswith(_API_ADD_MATERIAL):
            return json.dumps({"media_id": "cover-media-id"})
        if url.startswith(_API_ADD_DRAFT):
            # 草稿内容里应当已经是微信 URL，且不含本地路径
            payload = json.loads(body.decode("utf-8"))
            article = payload["articles"][0]
            assert "https://mmbiz.qpic.cn/body" in article["content"]
            assert "images/a.png" not in article["content"]
            assert article["thumb_media_id"] == "cover-media-id"
            assert article["title"] == "测试文章"
            return json.dumps({"media_id": "draft-media-id"})
        raise AssertionError(f"意外的请求：{url}")

    client = make_client(handler)
    result = publish_article(
        repo_root=tmp_path,
        metadata=metadata,
        output_dir=output_dir,
        html_path=html_path,
        client=client,
    )

    assert result.draft_media_id == "draft-media-id"
    assert result.uploaded_images == {"images/a.png": "https://mmbiz.qpic.cn/body"}
    assert result.replaced_images == 1
    assert result.uploaded_cover == "cover-media-id"

    # 回填后的 HTML 落盘，供"接口能用但草稿不满意"时手工粘贴
    published = output_dir / PUBLISHED_HTML_NAME
    assert published.is_file()
    assert "https://mmbiz.qpic.cn/body" in published.read_text(encoding="utf-8")


def test_没有凭据时抛_PublishNotConfigured(tmp_path: Path, built_article) -> None:
    """缺凭据要给"去配置"的指引，而不是栈回溯。"""
    output_dir, metadata, html_path = built_article
    with pytest.raises(PublishNotConfigured) as excinfo:
        publish_article(
            repo_root=tmp_path,
            metadata=metadata,
            output_dir=output_dir,
            html_path=html_path,
            client=None,
            credentials=None,
        )
    assert excinfo.value.code == "publish_not_configured"
    assert "INLOOP_WECHAT_APPID" in excinfo.value.hint
    assert "白名单" in excinfo.value.hint


def test_缺少封面时拒绝建草稿(built_article) -> None:
    """微信要求草稿必须有封面；缺了要当场报错而不是建出一个坏草稿。"""
    output_dir, metadata, html_path = built_article
    metadata["images"] = [e for e in metadata["images"] if e["kind"] == "body"]

    def handler(url, method, body, headers):
        if url.startswith(_API_TOKEN):
            return json.dumps({"access_token": "tok", "expires_in": 7200})
        return json.dumps({"url": "https://mmbiz.qpic.cn/body"})

    with pytest.raises(WechatError) as excinfo:
        publish_article(
            repo_root=output_dir,
            metadata=metadata,
            output_dir=output_dir,
            html_path=html_path,
            client=make_client(handler),
        )
    assert excinfo.value.code == "cover_missing"


def test_图片上传失败时整体中止(built_article) -> None:
    """产出半套正文比直接报错更糟，因此一张图失败就中止。"""
    output_dir, metadata, html_path = built_article

    def handler(url, method, body, headers):
        if url.startswith(_API_TOKEN):
            return json.dumps({"access_token": "tok", "expires_in": 7200})
        return json.dumps({"errcode": 40001, "errmsg": "invalid credential"})

    client = make_client(handler)
    with pytest.raises(WechatError) as excinfo:
        publish_article(
            repo_root=output_dir,
            metadata=metadata,
            output_dir=output_dir,
            html_path=html_path,
            client=client,
        )
    assert "上传正文图片失败" in str(excinfo.value)
    assert excinfo.value.code == "wechat_api_error"


def test_图片上传了但正文里找不到对应_src_时给出警告(built_article) -> None:
    """静默不匹配会让用户以为图片已经就位，必须警告。"""
    output_dir, metadata, html_path = built_article
    html_path.write_text("<html><body><p>没有图片</p></body></html>", encoding="utf-8")

    def handler(url, method, body, headers):
        if url.startswith(_API_TOKEN):
            return json.dumps({"access_token": "tok", "expires_in": 7200})
        if url.startswith(_API_UPLOAD_IMG):
            return json.dumps({"url": "https://mmbiz.qpic.cn/body"})
        if url.startswith(_API_ADD_MATERIAL):
            return json.dumps({"media_id": "cover-id"})
        return json.dumps({"media_id": "draft-id"})

    result = publish_article(
        repo_root=output_dir,
        metadata=metadata,
        output_dir=output_dir,
        html_path=html_path,
        client=make_client(handler),
    )
    assert result.replaced_images == 0
    assert any("没有在正文里找到" in w for w in result.warnings)
