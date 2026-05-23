#!/usr/bin/env bash
# Run from anywhere: ./start.sh   or   bash start.sh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

python -m pip install -q -r requirements.txt

if lsof -i :8000 >/dev/null 2>&1; then
  echo "Port 8000 in use. Stopping existing uvicorn..."
  pkill -f "uvicorn app.main:app" 2>/dev/null || true
  sleep 1
fi

echo "Starting API at http://127.0.0.1:8000"
exec python -m uvicorn app.main:app --reload --port 8000
