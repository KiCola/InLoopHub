"""本地预览服务器。

用途：把构建产物在本机跑起来看，确认手机上读起来的样子（任务书 §13）。

两个刻意的选择：

- **只监听 127.0.0.1。** 预览是本地动作，不应该暴露到局域网。
- **只服务构建产物目录。** 服务器的作用是"看产物"，不是"浏览仓库"，
  因此把根目录限定在 ``dist/wechat/<slug>/``，不会顺带暴露源文件。
"""

from __future__ import annotations

import functools
import socket
import threading
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

#: 默认端口；被占用时向后顺延
DEFAULT_PORT = 8000
#: 顺延尝试次数
PORT_ATTEMPTS = 20

#: 监听地址（仅本机）
BIND_HOST = "127.0.0.1"


class PreviewError(RuntimeError):
    """预览服务无法启动。"""


class _QuietHandler(SimpleHTTPRequestHandler):
    """关掉逐条请求日志。

    默认实现会把每个请求打到 stderr，把构建提示冲得看不见。
    真正的错误（404 等）仍会显示在浏览器里。
    """

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002
        return

    def end_headers(self) -> None:
        # 预览页是本地临时文件，禁用缓存以免改了产物还看到旧页面
        self.send_header("Cache-Control", "no-store")
        super().end_headers()


def find_free_port(start: int = DEFAULT_PORT, attempts: int = PORT_ATTEMPTS) -> int:
    """从 ``start`` 起找一个可用端口。

    Raises:
        PreviewError: 连续多个端口都不可用。
    """
    for offset in range(attempts):
        candidate = start + offset
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                probe.bind((BIND_HOST, candidate))
            except OSError:
                continue
        return candidate

    raise PreviewError(
        f"端口 {start}–{start + attempts - 1} 都被占用，无法启动预览服务。\n"
        f"修正方法：用 --port 指定一个空闲端口。"
    )


def serve(directory: Path, *, port: int, open_browser: bool, path: str = "/") -> None:
    """启动预览服务并阻塞，直到用户中断。

    Args:
        directory: 要服务的产物目录。
        port: 端口。
        open_browser: 是否自动打开浏览器。
        path: 启动后打开的页面路径。
    """
    if not directory.is_dir():
        raise PreviewError(
            f"产物目录不存在：{directory}\n"
            f"修正方法：先执行构建，或检查文章 slug 是否正确。"
        )

    handler = functools.partial(_QuietHandler, directory=str(directory))
    try:
        server = ThreadingHTTPServer((BIND_HOST, port), handler)
    except OSError as exc:
        raise PreviewError(
            f"无法在 {BIND_HOST}:{port} 启动预览服务：{exc}\n"
            f"修正方法：换一个端口（--port）。"
        ) from exc

    url = f"http://{BIND_HOST}:{port}{path}"
    print(f"预览服务已启动：{url}")
    print(f"服务目录：{directory}")
    print("按 Ctrl+C 停止。")

    if open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n预览服务已停止。")
    finally:
        server.server_close()
