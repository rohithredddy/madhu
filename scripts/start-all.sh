#!/usr/bin/env bash
# Start all three parts of the application for development (docs/02 section 4):
#   Python engine  http://localhost:8000   (analyzer/.venv)
#   Java backend   http://localhost:8080   (backend/, Maven Wrapper)
#   React UI       http://localhost:5173   (frontend/, Vite)
# Open http://localhost:5173. Ctrl+C stops all three.
#
# Needs: analyzer/.venv with `pip install -e ".[dev]"`, a JDK 21, and `npm install`
# run once in frontend/. Data comes from data/ (XAIRCA_DATA_DIR overrides it).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY="$ROOT/analyzer/.venv/bin/python"
[ -x "$PY" ] || PY="$ROOT/analyzer/.venv/Scripts/python.exe"   # Windows Git Bash
if [ ! -x "$PY" ]; then
  echo "No analyzer/.venv found. Create it first: see analyzer/README.md" >&2
  exit 1
fi

pids=()
stop() {
  echo "stopping..."
  for pid in "${pids[@]}"; do kill "$pid" 2>/dev/null || true; done
}
trap stop EXIT INT TERM

echo "starting the Python engine on :8000"
(cd "$ROOT/analyzer" && "$PY" -m uvicorn service.app:app --host 127.0.0.1 --port 8000) &
pids+=($!)

echo "starting the Java backend on :8080 (the first start downloads Maven and dependencies)"
# The backend is started from backend/, so its default data dir ../data resolves to
# the project's data/ folder (decision 12).
(cd "$ROOT/backend" && ./mvnw -q spring-boot:run) &
pids+=($!)

echo "starting the React UI on :5173"
(cd "$ROOT/frontend" && npm run dev -- --strictPort) &
pids+=($!)

echo "open http://localhost:5173 once the backend logs 'Started XaiRcaApplication'"
wait
