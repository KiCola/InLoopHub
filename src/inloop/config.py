"""配置读取与仓库根定位。

设计要求（已在任务书复审中确认）：

- 程序的路径解析**不依赖当前工作目录**：通过向上查找标记文件定位仓库根，
  因此 ``inloop`` 在任意 cwd 下执行都指向同一个仓库。
- 配置只从 ``config/`` 下的 YAML 读取，配置文件是这些值的唯一事实源；
  本模块不做「代码里再写一份默认值」的事，避免两处定义互相漂移。
- **内容与工具解耦**（任务书 §3）：文章放在 ``content_root`` 指向的目录里，
  它可以在任意位置——本机任意路径、Obsidian 仓库、同步目录，甚至另一个 Git 仓库。
  工具仓库只负责程序本身。
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

#: 未配置内容目录时的兜底位置（相对仓库根）。
#: 保留它有两个用处：仓库自带的示例文章可直接跑通；测试不必依赖外部目录。
DEFAULT_CONTENT_DIR = "articles"

# 定位仓库根的标记：这些路径同时存在时，认为该目录就是仓库根。
# 之所以不只用 pyproject.toml，是因为它在任意 Python 项目里都会出现；
# 加上 config/ 后误判概率极低，且不依赖 .git（源码分发时可能没有 .git）。
_ROOT_MARKERS: tuple[Path, ...] = (
    Path("pyproject.toml"),
    Path(CONFIG_DIR_NAME) / SITE_CONFIG_NAME,
)

# 允许通过环境变量显式指定仓库根，便于测试与特殊部署。
_ROOT_ENV_VAR = "INLOOP_ROOT"

#: 内容目录的环境变量名（优先级低于 ``--content`` 参数，高于配置文件）
_CONTENT_ENV_VAR = "INLOOP_CONTENT"

#: 构建产物目录的环境变量名
_DIST_ENV_VAR = "INLOOP_DIST"


class ConfigError(RuntimeError):
    """配置缺失或格式非法。

    错误信息必须说明「哪里错了 + 怎么修」，见 AGENTS.md §4。

    ``code`` 是给**程序**判断用的（见 :mod:`inloop.jsonapi`）：
    插件需要区分"内容目录没配好，应当引导用户去设置界面"与"意外故障"，
    两者的界面反应完全不同。默认 ``config_invalid``。
    """

    def __init__(self, message: str, *, code: str = "config_invalid") -> None:
        super().__init__(message)
        self.code = code


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
        root: 工具仓库根目录。
        site: ``config/site.yaml`` 的 ``site`` 段。
        brand: ``config/site.yaml`` 的 ``brand`` 段。
        wechat: ``config/wechat.yaml`` 的 ``wechat`` 段。
        content: ``config/site.yaml`` 的 ``content`` 段（可为空映射）。
    """

    root: Path
    site: dict[str, Any]
    brand: dict[str, Any]
    wechat: dict[str, Any]
    content: dict[str, Any]

    def site_value(self, key: str) -> Any:
        """读取 ``site`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.site, key, f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}", "site")

    def brand_value(self, key: str) -> Any:
        """读取 ``brand`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.brand, key, f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}", "brand")

    def wechat_value(self, key: str) -> Any:
        """读取 ``wechat`` 段的一项，缺失时报错并给出文件名。"""
        return self._value(self.wechat, key, f"{CONFIG_DIR_NAME}/{WECHAT_CONFIG_NAME}", "wechat")

    def content_value(self, key: str, default: Any = None) -> Any:
        """读取 ``content`` 段的一项。

        与另外三个 different：``content`` 段**允许整段缺失**（内容目录是可选配置），
        因此这里在键不存在时返回 ``default`` 而不是报错。
        """
        return self.content.get(key, default)

    def resolve_content_root(self, override: Path | str | None = None) -> Path:
        """确定内容目录（任务书 §3.3 的解析顺序）。

        优先级：``override``（来自 ``--content``）> ``INLOOP_CONTENT`` 环境变量 >
        ``config/site.yaml`` 的 ``content.root`` > ``<仓库根>/articles``。

        Args:
            override: 命令行显式指定的内容目录。

        Returns:
            内容目录的绝对路径。

        Raises:
            ConfigError: 指定的目录不存在，或配置文件里的值不是字符串。
        """
        # 1) 命令行参数
        if override is not None:
            return _as_directory(override, "命令行参数 --content")

        # 2) 环境变量
        env_value = os.environ.get(_CONTENT_ENV_VAR)
        if env_value and env_value.strip():
            return _as_directory(env_value, f"环境变量 {_CONTENT_ENV_VAR}")

        # 3) 配置文件。
        # 注意：`root: ""` 表示"未配置"而不是"内容目录是空路径"——
        # 配置文件里留一个空值是最自然的写法，必须走兜底而不是报错。
        configured = self.content.get("root")
        if configured is not None and str(configured).strip():
            if not isinstance(configured, str):
                raise ConfigError(
                    f"配置项 `content.root` 必须是字符串，"
                    f"实际为 {type(configured).__name__}："
                    f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}\n"
                    f"修正方法：写成字符串路径，例如 `root: \"D:/我的文章\"`；"
                    f"不想用就留空，会回退到仓库内的 {DEFAULT_CONTENT_DIR}/。"
                )
            return _as_directory(
                configured, f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME} 的 content.root"
            )

        # 4) 兜底
        return self.root / DEFAULT_CONTENT_DIR

    def resolve_dist_root(self) -> Path:
        """确定构建产物目录。

        优先级：``INLOOP_DIST`` 环境变量 > ``config/site.yaml`` 的 ``content.dist`` >
        ``<仓库根>/dist``。

        产物是可再生的派生物，因此默认放在工具仓库内并已被 ``.gitignore`` 排除。
        允许改到别处是为了让"内容与工具分处不同磁盘"的部署也能把产物放到合适位置。
        """
        env_value = os.environ.get(_DIST_ENV_VAR)
        if env_value and env_value.strip():
            return Path(env_value).expanduser().resolve()

        configured = self.content.get("dist")
        if configured is not None and str(configured).strip():
            if not isinstance(configured, str):
                raise ConfigError(
                    f"配置项 `content.dist` 必须是字符串，"
                    f"实际为 {type(configured).__name__}："
                    f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}\n"
                    f"修正方法：写成字符串路径，或留空使用默认的 dist/。"
                )
            return Path(configured).expanduser().resolve()

        return self.root / "dist"

    @staticmethod
    def _value(section: dict[str, Any], key: str, filename: str, section_name: str) -> Any:
        if key not in section:
            raise ConfigError(
                f"配置项缺失：{filename} 的 `{section_name}.{key}`\n"
                f"修正方法：在该段落下补上 `{key}:`，取值见任务书 §20。"
            )
        return section[key]


def _as_directory(value: Path | str, source: str) -> Path:
    """把取值解析为已存在的目录路径；不存在时给出可定位的错误。"""
    candidate = Path(value).expanduser().resolve()
    if not candidate.is_dir():
        raise ConfigError(
            f"内容目录不存在：{candidate}\n"
            f"  来源：{source}\n"
            f"修正方法：确认路径拼写正确、目录已创建；"
            f"或改用 `--content <路径>` 临时指定另一个目录。",
            code="content_root_missing",
        )
    return candidate


def load_config(root: Path | None = None) -> Config:
    """读取仓库配置（带缓存）。

    缓存**按实际解析出的仓库根**分别保留。

    为什么不能简单加 ``@lru_cache``：``root=None`` 时实际根来自
    ``INLOOP_ROOT`` 环境变量，而环境变量不参与缓存键——同一个进程里
    改了环境变量仍会拿到旧配置。测试与多仓库场景都会踩到。
    因此这里显式以解析后的根作为缓存键。

    Args:
        root: 仓库根目录；为 None 时自动定位。

    Returns:
        解析后的 :class:`Config`。

    Raises:
        ConfigError: 目录或配置内容不合法。
    """
    return _load_config_cached(root or repo_root())


@lru_cache(maxsize=8)
def _load_config_cached(resolved_root: Path) -> Config:
    """按仓库根缓存的实现细节。"""
    config_dir = resolved_root / CONFIG_DIR_NAME

    site_doc = _read_yaml(config_dir / SITE_CONFIG_NAME)
    wechat_doc = _read_yaml(config_dir / WECHAT_CONFIG_NAME)

    # 顺序很重要：**先取出 content 段再删键**。
    # 反过来写（先 pop 再读）会永远读到空映射——配置里填了内容目录也不生效，
    # 而且静默回退到 <repo>/articles，退出码仍是 0，用户无从判断原因。
    # 这个 bug 真的写出来过，由独立审核发现。
    content_section = _optional_mapping(site_doc, "content")
    site_doc.pop("content", None)  # content 是顶层段，不属于 site

    return Config(
        root=resolved_root,
        site=_require_mapping(site_doc, "site", config_dir / SITE_CONFIG_NAME),
        brand=_require_mapping(site_doc, "brand", config_dir / SITE_CONFIG_NAME),
        wechat=_require_mapping(wechat_doc, "wechat", config_dir / WECHAT_CONFIG_NAME),
        content=content_section,
    )


def _optional_mapping(data: dict[str, Any], key: str) -> dict[str, Any]:
    """取出一个可选映射段；缺失或为 null 时返回空映射。

    与 :func:`_require_mapping` 的区别：这里不报错。用于「整段可以不存在」的配置，
    例如 ``content``（内容目录是可选配置，不配就走兜底）。
    """
    value = data.get(key)
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ConfigError(
            f"配置段 `{key}` 必须是映射，实际为 {type(value).__name__}："
            f"{CONFIG_DIR_NAME}/{SITE_CONFIG_NAME}\n"
            f"修正方法：把 `{key}:` 下的内容写成键值对，例如：\n"
            f"  {key}:\n"
            f"    root: \"D:/我的文章\""
        )
    return value
