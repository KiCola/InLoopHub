"""微信公众号 API 客户端（任务书 §19、§25 第 17–19 项）。

## 为什么这个模块存在

图片在微信端**必须在编辑器里逐张手动上传**（已实测：微信不抓本地路径、
也不抓外链）。要省掉这一步，唯一途径是官方素材接口：上传图片换取微信自己的
URL，再把正文里的本地路径替换掉，最后创建草稿。

## 凭据

按以下优先级读取（都不写死在代码里，AGENTS.md §4）：

1. 显式传入的 :class:`WechatCredentials`
2. 环境变量 ``INLOOP_WECHAT_APPID`` / ``INLOOP_WECHAT_SECRET``
3. 凭据文件（默认 ``<工具仓库>/config/wechat.credentials.json``，**不入 Git**）

## ⚠️ 未验证的接口路径

微信的接口路径与参数取自公开文档，**本机没有凭据、也没有固定 IP，
因此这些调用从未真正成功执行过**。首次在有凭据的环境里使用时请核对
``_API_*`` 常量是否与当前官方文档一致，不一致就改常量——不要在调用点硬编码。

## IP 白名单

微信要求把**发起请求的 IP** 加入公众号后台白名单。家庭宽带的公网 IP 通常
不稳定，因此这一层在那种环境下无法稳定工作，需要固定 IP 的出口（例如一台
最便宜的云服务器做代理）。
"""

from __future__ import annotations

import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# --- 接口地址（未验证，见模块文档）---------------------------------------

_API_ORIGIN = "https://api.weixin.qq.com"
#: 取 access_token
_API_TOKEN = _API_ORIGIN + "/cgi-bin/token"
#: 上传图文正文内的图片，返回微信托管的 URL
_API_UPLOAD_IMG = _API_ORIGIN + "/cgi-bin/media/uploadimg"
#: 上传永久素材，用于封面（草稿的 thumb_media_id 需要它）
_API_ADD_MATERIAL = _API_ORIGIN + "/cgi-bin/material/add_material"
#: 新建草稿
_API_ADD_DRAFT = _API_ORIGIN + "/cgi-bin/draft/add"

#: access_token 有效期 7200 秒；提前 5 分钟刷新，避免边界失败
_TOKEN_SAFETY_MARGIN = 300

#: 单次请求超时
_TIMEOUT_SECONDS = 30


class WechatError(RuntimeError):
    """微信 API 调用失败。

    ``code`` 是给程序判断用的（见 :mod:`inloop.jsonapi`），
    ``errcode`` 是微信返回的原始错误码，便于查官方文档。
    """

    def __init__(
        self,
        message: str,
        *,
        code: str = "wechat_error",
        errcode: int | None = None,
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.errcode = errcode
        self.hint = hint


# --- 凭据 -----------------------------------------------------------------


#: 凭据文件名（相对工具仓库的 config/ 目录）
CREDENTIALS_FILE_NAME = "wechat.credentials.json"


@dataclass(frozen=True)
class WechatCredentials:
    """公众号凭据。

    Attributes:
        appid: 公众号的 AppID。
        secret: 公众号的 AppSecret。**不要提交进任何仓库。**
        source: 凭据来源（用于诊断输出），例如"环境变量"或某个文件路径。
    """

    appid: str
    secret: str
    source: str = "显式传入"

    def masked(self) -> str:
        """供展示用的脱敏形式——日志与界面里都不该出现完整 secret。"""
        tail = self.secret[-4:] if len(self.secret) >= 4 else ""
        return f"appid={self.appid} secret=***{tail}（来源：{self.source}）"


def load_credentials(
    repo_root: Path,
    *,
    explicit: WechatCredentials | None = None,
) -> WechatCredentials | None:
    """按优先级读取凭据；读不到时返回 None（而不是抛异常）。

    返回 None 让调用方可以"检测到没凭据就降级为复制模式"，
    而不是把"没配置"当成错误——那是正常状态（任务书 §18 的半自动流程）。
    """
    if explicit is not None:
        return explicit

    appid = os.environ.get("INLOOP_WECHAT_APPID", "").strip()
    secret = os.environ.get("INLOOP_WECHAT_SECRET", "").strip()
    if appid and secret:
        return WechatCredentials(appid, secret, source="环境变量 INLOOP_WECHAT_APPID")

    path = repo_root / "config" / CREDENTIALS_FILE_NAME
    if not path.is_file():
        return None

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise WechatError(
            f"凭据文件读不出来：{path}\n原始错误：{exc}",
            code="credentials_invalid",
            hint='修正方法：确认它是合法 JSON，形如 {"appid": "wx...", "secret": "..."}；'
            "或删除该文件改用环境变量。",
        ) from exc

    file_appid = str(data.get("appid", "")).strip()
    file_secret = str(data.get("secret", "")).strip()
    if not file_appid or not file_secret:
        raise WechatError(
            f"凭据文件缺少 appid 或 secret：{path}",
            code="credentials_invalid",
            hint='修正方法：补全为 {"appid": "wx...", "secret": "..."}。',
        )
    return WechatCredentials(file_appid, file_secret, source=str(path))


# --- 客户端 ---------------------------------------------------------------


@dataclass
class WechatClient:
    """微信 API 的最小客户端。

    只实现"把文章变成草稿"所需的三个接口：取 token、上传正文图片、建草稿。
    刻意不实现群发——任务书 §18 明确 V1 **禁止自动群发**。
    """

    credentials: WechatCredentials
    #: 注入用：便于测试时替换掉真实网络调用
    transport: Any = None
    _token: str = ""
    _token_expires_at: float = field(default=0.0)

    # --- 底层请求 ---------------------------------------------------------

    def _request(
        self,
        url: str,
        *,
        params: dict[str, str] | None = None,
        method: str = "GET",
        body: bytes | None = None,
        headers: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        """发一次请求并把响应解析成 JSON。

        所有失败都在这里统一转成 :class:`WechatError`，调用点不必各自处理网络异常。

        ``transport`` 注入用于测试：它**返回原始响应字节**（而不是解析好的 dict），
        这样"解析 + 检查 errcode"这段逻辑对真实与测试路径是同一条——
        否则测试会绕过错误处理，测出一个与线上不同的行为。
        """
        target = url
        if params:
            target = f"{url}?{urllib.parse.urlencode(params)}"

        if self.transport is not None:
            raw = self.transport(target, method, body, headers or {})
        else:
            request = urllib.request.Request(  # noqa: S310 - 域名是常量，不接受外部输入
                target, data=body, method=method, headers=headers or {}
            )
            try:
                with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:  # noqa: S310
                    raw = response.read()
            except urllib.error.HTTPError as exc:
                raise WechatError(
                    f"微信接口返回 HTTP {exc.code}：{target}",
                    code="wechat_http_error",
                    hint="通常是网络或代理问题；也可能是出口 IP 不在白名单导致被拦。",
                ) from exc
            except urllib.error.URLError as exc:
                raise WechatError(
                    f"连不上微信接口：{target}\n原始错误：{exc.reason}",
                    code="wechat_unreachable",
                    hint="检查网络与代理设置。",
                ) from exc

        if isinstance(raw, str):
            raw = raw.encode("utf-8")

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WechatError(
                f"微信接口返回的内容不是 JSON：{raw[:200]!r}",
                code="wechat_bad_response",
                hint="这通常说明请求被网关拦截了（例如出口 IP 不在白名单）。",
            ) from exc

        if not isinstance(payload, dict):
            raise WechatError(
                f"微信接口返回了意外的结构：{payload!r}",
                code="wechat_bad_response",
            )

        # 微信用 errcode != 0 表示失败，HTTP 状态码仍是 200
        errcode = payload.get("errcode")
        if errcode:
            raise self._api_error(int(errcode), str(payload.get("errmsg", "")), target)
        return payload

    @staticmethod
    def _api_error(errcode: int, errmsg: str, target: str) -> WechatError:
        """把微信错误码翻成"哪里错了 + 怎么改"。

        只覆盖已知的高频错误；其余保留原始 errcode 便于查官方文档。
        """
        known: dict[int, str] = {
            40001: "AppSecret 不正确，或 access_token 已失效。检查凭据配置。",
            40013: "AppID 不合法。检查是否把订阅号/服务号的 AppID 弄混了。",
            40164: (
                "调用方 IP 不在白名单。需要在公众号后台"
                "（设置与开发 → 基本配置 → IP 白名单）把当前出口 IP 加进去。"
            ),
            41001: "缺少 access_token 参数。这通常是程序缺陷，请反馈。",
            45009: "接口调用超过每日限额。",
            48001: "该接口未授权。个人订阅号没有部分接口权限。",
        }
        hint = known.get(
            errcode, "对照官方文档的错误码说明：https://developers.weixin.qq.com/doc/offiaccount/"
        )
        return WechatError(
            f"微信接口报错 {errcode}：{errmsg}（{target}）",
            code="wechat_api_error",
            errcode=errcode,
            hint=hint,
        )

    # --- 具体接口 ---------------------------------------------------------

    def access_token(self, *, force: bool = False) -> str:
        """取 access_token，带进程内缓存（有效期 7200 秒）。"""
        now = time.time()
        if not force and self._token and now < self._token_expires_at:
            return self._token

        payload = self._request(
            _API_TOKEN,
            params={
                "grant_type": "client_credential",
                "appid": self.credentials.appid,
                "secret": self.credentials.secret,
            },
        )
        token = str(payload.get("access_token", ""))
        if not token:
            raise WechatError(
                "微信没有返回 access_token。",
                code="wechat_no_token",
                hint="检查 AppID 与 AppSecret 是否正确；也确认这台机器的出口 IP 已在白名单里。",
            )
        expires_in = int(payload.get("expires_in", 7200))
        self._token = token
        self._token_expires_at = now + max(60, expires_in - _TOKEN_SAFETY_MARGIN)
        return token

    def upload_body_image(self, path: Path) -> str:
        """上传正文图片，返回微信托管的 URL。

        这是替代"在编辑器里逐张手动上传"的关键一步：
        拿到 URL 后把它写回正文 HTML，粘贴时图片就能直接显示。

        Raises:
            WechatError: 文件不存在或接口报错。
        """
        if not path.is_file():
            raise WechatError(
                f"要上传的图片不存在：{path}",
                code="image_not_found",
                hint="先运行 `inloop build-wechat` 生成产物，再用产物里的 images/ 目录。",
            )

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body, headers = _multipart(
            fields={},
            files={"media": (path.name, path.read_bytes(), content_type)},
        )
        payload = self._request(
            _API_UPLOAD_IMG,
            params={"access_token": self.access_token()},
            method="POST",
            body=body,
            headers=headers,
        )
        url = str(payload.get("url", ""))
        if not url:
            raise WechatError(
                f"上传图片成功但没返回 url：{path.name}",
                code="wechat_bad_response",
            )
        return url

    def upload_cover_material(self, path: Path) -> str:
        """上传封面为**永久素材**，返回 ``media_id``。

        草稿的 ``thumb_media_id`` 需要永久素材的 media_id（临时素材不适用于草稿封面）。
        """
        if not path.is_file():
            raise WechatError(
                f"封面文件不存在：{path}",
                code="image_not_found",
                hint="确认 front matter 的 cover 指向的文件已在文章目录里。",
            )

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        body, headers = _multipart(
            fields={"type": "image"},
            files={"media": (path.name, path.read_bytes(), content_type)},
        )
        payload = self._request(
            _API_ADD_MATERIAL,
            params={"access_token": self.access_token()},
            method="POST",
            body=body,
            headers=headers,
        )
        media_id = str(payload.get("media_id", ""))
        if not media_id:
            raise WechatError(
                "上传封面成功但没返回 media_id。",
                code="wechat_bad_response",
            )
        return media_id

    def add_draft(
        self,
        *,
        title: str,
        html: str,
        thumb_media_id: str,
        author: str = "",
        digest: str = "",
    ) -> str:
        """新建草稿，返回草稿的 ``media_id``。

        **不群发。** 任务书 §18 明确 V1 禁止自动群发，草稿创建后由人在后台
        预览、确认、发布。
        """
        article: dict[str, Any] = {
            "title": title,
            "content": html,
            "thumb_media_id": thumb_media_id,
            "need_open_comment": 0,
            "only_fans_can_comment": 0,
        }
        if author:
            article["author"] = author
        if digest:
            article["digest"] = digest

        body = json.dumps({"articles": [article]}, ensure_ascii=False).encode("utf-8")
        payload = self._request(
            _API_ADD_DRAFT,
            params={"access_token": self.access_token()},
            method="POST",
            body=body,
            headers={"Content-Type": "application/json; charset=utf-8"},
        )
        media_id = str(payload.get("media_id", ""))
        if not media_id:
            raise WechatError(
                "创建草稿成功但没返回 media_id。",
                code="wechat_bad_response",
            )
        return media_id


def _multipart(
    *, fields: dict[str, str], files: dict[str, tuple[str, bytes, str]]
) -> tuple[bytes, dict[str, str]]:
    """手写 multipart/form-data 编码。

    为什么不用 ``requests``：任务书 §21 的依赖清单里没有 HTTP 客户端，
    而这里只需要上传文件这一种形态。用标准库就不必新增依赖。
    """
    boundary = f"----inloop{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(f"{value}\r\n".encode())

    for name, (filename, content, content_type) in files.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(
            f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode()
        )
        chunks.append(f"Content-Type: {content_type}\r\n\r\n".encode())
        chunks.append(content)
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode())
    return b"".join(chunks), {"Content-Type": f"multipart/form-data; boundary={boundary}"}
