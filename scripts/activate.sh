#!/usr/bin/env bash
# 激活本项目的虚拟环境，供 bash / zsh / Git Bash / MSYS2 / WSL 使用。
#
# 用法（**必须用 source**，否则改动的 PATH 只作用于子进程，退出即失效）：
#
#     source scripts/activate.sh
#
# 关于"为什么不直接用虚拟环境自带的 activate"：
# **自带脚本本身没问题**，`source .venv/Scripts/activate` 在 Git Bash 里同样有效
# （已实测确认）。漏掉 `source` 才是 `inloop: command not found` 的真正原因——
# 直接执行会在子进程里改 PATH，父 shell 收不到。
#
# 本脚本的额外价值只有两点：按当前平台习惯设置 PATH，并把结果**明确报告**出来
# （激活了哪个环境、版本号、可用的命令形式），省去"我到底激活成功没有"的猜测。

set -u

# 定位仓库根：本脚本位于 <root>/scripts/ 下
_script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
_repo_root="$(cd -- "${_script_dir}/.." && pwd)"

if [ -f "${_repo_root}/.venv/Scripts/inloop.exe" ]; then
  # Windows 版虚拟环境（Git Bash / MSYS2 / CMD 生成的都一样）
  _bin_dir="${_repo_root}/.venv/Scripts"
  _inloop="${_bin_dir}/inloop.exe"
elif [ -x "${_repo_root}/.venv/bin/inloop" ]; then
  # 类 Unix 虚拟环境
  _bin_dir="${_repo_root}/.venv/bin"
  _inloop="${_bin_dir}/inloop"
else
  echo "✗ 没有找到可用的虚拟环境。" >&2
  echo "  期望位置：${_repo_root}/.venv/Scripts/inloop.exe 或 ${_repo_root}/.venv/bin/inloop" >&2
  echo "  修正方法：先在本仓库根目录执行" >&2
  echo "      python -m venv .venv" >&2
  echo "      .venv/Scripts/python.exe -m pip install --no-build-isolation -e \".[dev]\"" >&2
  return 1 2>/dev/null || exit 1
fi

# 把虚拟环境的 bin 目录放到 PATH 最前面。
# 路径用 POSIX 形式（/e/... 或 /home/...），bash 才认得。
case ":${PATH}:" in
  *":${_bin_dir}:"*) ;; # 已在 PATH 中，不重复添加
  *) PATH="${_bin_dir}:${PATH}" ;;
esac
export PATH

# 同时设置 VIRTUAL_ENV，让其他工具（pip 等）也能识别
export VIRTUAL_ENV="${_repo_root}/.venv"
unset PYTHONHOME 2>/dev/null || true

echo "✓ 已激活虚拟环境：${VIRTUAL_ENV}"
echo "  版本：$("${_inloop}" version 2>/dev/null || echo '（无法读取，请检查安装）')"
echo
echo "  可用命令形式："
echo "      inloop check 005-practice-run          # 已加入 PATH，可直接用"
echo "      ${_inloop#"${_repo_root}"/} check 005-practice-run"
echo
echo "  注意：仅对**当前 shell** 生效。新开终端需要重新 source 本脚本。"

unset _script_dir _repo_root _bin_dir _inloop
