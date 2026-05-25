#!/usr/bin/env bash
# 供 Makefile 调用：确保 uv 可用，并执行 launcher.py --setup-only
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PIANKE_ROOT="$ROOT"
export LC_ALL="${LC_ALL:-en_US.UTF-8}"
export LANG="${LANG:-en_US.UTF-8}"

MODES="${PIANKE_MODES:-all}"

find_uv() {
  if command -v uv &>/dev/null; then
    command -v uv
    return
  fi
  for cand in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    if [ -x "$cand" ]; then
      echo "$cand"
      return
    fi
  done
}

UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  echo "→ 未找到 uv，正在安装（约 30MB，仅首次）..."
  if ! command -v curl &>/dev/null; then
    echo "❌ 需要 curl 才能安装 uv" >&2
    exit 1
  fi
  curl -LSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"
  UV="$(find_uv || true)"
fi
if [ -z "$UV" ]; then
  echo "❌ uv 安装失败，请手动执行: curl -LSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

echo "→ 准备 Python 虚拟环境与依赖（模式: ${MODES}，uv + pyproject.toml）..."
cd "$ROOT"
exec "$UV" run --python ">=3.10" -- \
  python scripts/launcher.py --setup-only --no-update --modes "$MODES"
