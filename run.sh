#!/usr/bin/env bash
# FinCompass 1.0.0 - one-click local run (macOS / Linux)
set -e
cd "$(dirname "$0")"
if [ ! -x ".venv/bin/python" ]; then
  echo "Creating virtual environment..."
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
echo "Installing / updating dependencies..."
python -m pip install --upgrade pip >/dev/null
pip install -r requirements.txt
[ -f .env ] || cp .env.example .env
echo "Starting FinCompass at http://127.0.0.1:8000  (Ctrl+C to stop)"
exec python -m uvicorn api:app --host 127.0.0.1 --port 8000
