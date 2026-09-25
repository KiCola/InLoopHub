"""文件写入的小工具。

存在的理由只有一个：**Windows 上原子替换会被瞬时占用打断**。

``Path.replace`` 在目标文件正被其他进程短暂持有（索引服务、杀毒扫描、
编辑器预览服务）时会抛 ``PermissionError``。同一个文件被连续构建多次、
或多个构建并行时尤其容易出现。这种失败是瞬时的，重试一次即可成功，
但如果不重试，用户会看到莫名其妙的"拒绝访问"。

因此这里提供 :func:`write_text` 与 :func:`write_bytes`：先写临时文件，
再带重试地替换目标——既保证不会留下半截文件，也不会被瞬时占用打断。
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

#: 替换失败时的重试次数与间隔。总等待时间约 0.5 秒，
#: 足以跨过索引/扫描造成的瞬时占用，又不会掩盖真正的权限问题。
_RETRY_ATTEMPTS = 8
_RETRY_DELAY_SECONDS = 0.06


def write_text(path: Path, content: str, *, encoding: str = "utf-8") -> Path:
    """写文本文件：UTF-8、LF、原子替换、带重试。

    Args:
        path: 目标路径，父目录会自动创建。
        content: 文件内容。
        encoding: 编码，默认 UTF-8。

    Returns:
        实际写入的路径。
    """
    data = content.encode(encoding)
    return write_bytes(path, data)


def write_bytes(path: Path, data: bytes) -> Path:
    """写二进制文件：原子替换、带重试。"""
    path.parent.mkdir(parents=True, exist_ok=True)

    # 用唯一临时名，避免并发写同一目标时互相覆盖临时文件
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    temp_path = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(data)
        _replace_with_retry(temp_path, path)
    except BaseException:
        temp_path.unlink(missing_ok=True)
        raise
    return path


def _replace_with_retry(source: Path, target: Path) -> None:
    """原子替换目标文件，遇瞬时占用时重试。"""
    last_error: OSError | None = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            source.replace(target)
            return
        except PermissionError as exc:
            # 目标被短暂占用：等待后重试
            last_error = exc
            time.sleep(_RETRY_DELAY_SECONDS * (attempt + 1))

    raise PermissionError(
        f"无法写入文件：{target}\n"
        f"原始错误：{last_error}\n"
        f"修正方法：确认该文件没有被其他程序占用（编辑器、预览服务、同步盘），"
        f"然后重试。"
    ) from last_error
