#!/usr/bin/env bash
# Serve Kev-4B for performance-emotion decisions.
# Uses GPU 0. The Huayin TTS process stays on GPU 1.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
KEV_DIR="${KEV_DIR:-$(cd "$ROOT/.." && pwd)/kev}"
PORT="${KEV_PORT:-8009}"

if [[ ! -f "$KEV_DIR/pyproject.toml" ]]; then
  echo "Kev checkout not found at $KEV_DIR" >&2
  echo "Clone with: gh repo clone jaredpalmer/kev \"$KEV_DIR\"" >&2
  exit 1
fi

export CUDA_VISIBLE_DEVICES="${CUDA_VISIBLE_DEVICES:-0}"
# uv run 会按锁文件同步环境，socksio 留不住。改走已有的 HTTP 代理。
unset ALL_PROXY all_proxy
cd "$KEV_DIR"
exec uv run --extra serve python -m kev.serve --run jaredpalmer/kev-4b --port "$PORT"
