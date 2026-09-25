"""配置读取与仓库根定位。

设计要求（已在任务书复审中确认）：

- 程序的路径解析**不依赖当前工作目录**：通过向上查找标记文件定位仓库根，
  因此 ``inloop`` 在任意 cwd 下执行都指向同一个仓库。
- 配置只从 ``config/`` 下的 YAML 读取，配置文件是这些值的唯一事实源；
  本模块不做「代码里再写一份默认值」的事，避免两处定义互相漂移。
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

SITE_CONFIG_NAME = "site.yaml"
WECHAT_CONFIG_NAME = "wechat.yaml"
CONFIG_DIR_NAME = "config"

# 定位仓库根的标记：这些路径同时存在时，认为该目录就是仓库根。
# 之所以不只用 pyproject.toml，是因为它在任意 Python 项目里都会出现；
# 加上 config/ 后误判概率极低，且不依赖 .git（源码分发时可能没有 .git）。
_ROOT_MARKERS: tuple[Path, ...] = (
    Path("pyproject.toml"),
    Path(CONFIG_DIR_NAME) / SITE_CONFIG_NAME,
)

# 允许通过环境变量显式指定仓库根，便于测试与特殊部署。
_ROOT_ENV_VAR = "INLOOP_ROOT"


class ConfigError(RuntimeError):
    """配置缺失或格式非法。

    错误信息必须说明「哪里错了 + 怎么修」，见 AGENTS.md §4。
    """


def repo_root(start: Path | None = None) -> Path:
    """定位仓库根目录。

    Args:
        start: 查找起点，默认从本文件所在位置开始。

    Returns:
        仓库根目录的绝对路径。

    Raises:
        ConfigError: 向上找到文件系统根仍未发现标记文件。
    """
    env_root = os.environ.get(_ROOT_ENV_VAR)
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if not candidate.is_dir():
            raise ConfigError(
                f"环境变量 {_ROOT_ENV_VAR} 指向的目录不存在：{candidate}\n"
                f"修正方法：把它改为本仓库根目录的路径，或删除该环境变量。"
            )
        return candidate

    current = (start or Path(__file__)).resolve()
    if current.is_file():
        current = current.parent

    for candidate in (current, *current.parents):
        if all((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate

    raise ConfigError(
        "未能定位仓库根目录：从 "
        f"{current} 向上直到文件系统根，都没有同时找到 "
        f"{' 与 '.join(str(m) for m in _ROOT_MARKERS)}。\n"
        f"修正方法：在仓库根目录下执行命令，或设置环境变量 {_ROOT_ENV_VAR} 指向仓库根。"
    )


def _read_yaml(path: Path) -> dict[str, Any]:
    """读取一个 YAML 文件并要求顶层是映射。"""
    if not path.is_file():
        raise ConfigError(
            f"缺少配置文件：{path}\n"
            f"修正方法：确认文件存在，且没有被误删或改名。"
        )

    try:
        # 只允许 safe_load，禁止 yaml.load
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(
            f"配置文件不是合法 YAML：{path}\n"
            f"原始错误：{exc}\n"
            f"修正方法：检查缩进是否为空格（不能使用 Tab）、冒号后是否有空格。"
        ) from exc

    if data is None:
        raise ConfigError(
            f"配置文件内容为空：{path}\n"
            f"修正方法：按任务书 §20 补齐配置项。"
        )

    if not isinstance(data, dict):
        raise ConfigError(
            f"配置文件顶层必须是映射（键值对），实际为 {type(data).__name__}：{path}\n"
            f"修正方法：确保顶层是形如 `site:` / `wechat:` 的映射结构。"
        )

    return data


def _require_mapping(data: dict[str, Any], key: str, path: Path) -> dict[str, Any]:
    """取出一个必须存在且为映射的顶层键。"""
    if key not in data:
        raise ConfigError(
            f"配置文件缺少顶层键 `{key}`：{path}\n"
            f"修正方法：按任务书 §20 补齐 `{key}:` 段落。"
        )

    value = data[key]
    if not isinstance(value, dict):
        raise ConfigError(
            f"配置项 `{key}` 必须是映射，实际为 {type(value).__name__}：{path}\n"
            f"修正方法：把 `{key}:` 下的内容写成键值对。"
        )

    return value


@dataclass(frozen=True)
class Config:
    """已解析的仓库配置。

    Attributes:
        root: 仓库根目录。
        site: ``config/site.yaml`` 的 ``site`` 段。
        brand: ``config/site.yaml`` 的 ``brand`` 段。
        wechat: ``config/wechat.yaml`` 的 ``wechat`` 段。
    """

    root: Path
    site: dict[str, Any]
    brand: dict[str, Any]
    wechat: dict[str, Any]

    def site_value(self, key: str) -> Any:
        """读取 ``site`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.site, key, f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}", "site")

    def brand_value(self, key: str) -> Any:
        """读取 ``brand`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.brand, key, f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}", "brand")

    def wechat_value(self, key: str) -> Any:
        """读取 ``wechat`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.wechat, key, f"{CONFIG_DIR_NAME}/{WECHAT_CONFIG_NAME}", "wechat")

    @staticmethod
    def _value(section: dict[str, Any], key: str, filename: str, section_name: str) -> Any:
        if key not in section:
            raise ConfigError(
                f"配置项缺失：{filename} 的 `{section_name}.{key}`\n"
                f"修正方法：在该段落下补上 `{key}:`，取值见任务书 §20。"
            )
        return section[key]


@lru_cache(maxsize=1)
def load_config(root: Path | None = None) -> Config:
    """读取并缓存仓库配置。

    Args:
        root: 仓库根目录；为 None 时自动定位。

    Returns:
        解析后的 :class:`Config`。

    Raises:
        ConfigError: 目录或配置内容不合法。
    """
    resolved_root = root or repo_root()
    config_dir = resolved_root / CONFIG_DIR_NAME

    site_doc = _read_yaml(config_dir / SITE_CONFIG_NAME)
    wechat_doc = _read_yaml(config_dir / WECHAT_CONFIG_NAME)

    return Config(
        root=resolved_root,
        site=_require_mapping(site_doc, "site", config_dir / SITE_CONFIG_NAME),
        brand=_require_mapping(site_doc, "brand", config_dir / SITE_CONFIG_NAME),
        wechat=_require_mapping(wechat_doc, "wechat", config_dir / WECHAT_CONFIG_NAME),
    )
