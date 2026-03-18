#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-5000}"

if ! command -v python >/dev/null 2>&1; then
  echo "找不到 python，請先安裝 Python 3.10+" >&2
  exit 1
fi

echo "[1/2] 安裝相依套件..."
python -m pip install -r requirements.txt

echo "[2/2] 啟動服務：http://127.0.0.1:${PORT}"
exec python app.py --host "$HOST" --port "$PORT"
