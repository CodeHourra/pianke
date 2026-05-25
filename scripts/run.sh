#!/usr/bin/env bash
# 片刻 — 启动脚本（uv + pyproject.toml）
#
# 第一次运行：自动 uv sync 并启动
# 任何参数都会透传给 app.py（如 --port 8080 --no-browser）

set -euo pipefail
cd "$(dirname "$0")/.."
export PIANKE_ROOT="$(pwd)"

find_uv() {
  if command -v uv &>/dev/null; then command -v uv; return; fi
  for cand in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
    [ -x "$cand" ] && echo "$cand" && return
  done
}

UV="$(find_uv || true)"
if [ -z "$UV" ]; then
  echo "❌ 未找到 uv。请安装: curl -LSf https://astral.sh/uv/install.sh | sh" >&2
  exit 1
fi

export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

MODES="${PIANKE_MODES:-all}"
echo "▶ uv sync（模式: ${MODES}）..."
"$UV" run --python ">=3.10" -- python scripts/launcher.py --setup-only --no-update --modes "$MODES"

echo "▶ 启动 pic_selecter..."
exec "$UV" run --python ">=3.10" -- python app.py "$@"
