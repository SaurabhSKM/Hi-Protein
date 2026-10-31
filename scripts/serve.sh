#!/usr/bin/env bash
# Start the whole app (API + built frontend) on a single port.
#
# One port is deliberate. In a cloud workspace usually only one port is forwarded,
# and running a separate Vite dev server adds a host check and a proxy hop that both
# have to be configured correctly. Serving the built bundle from the API process
# means one origin, no CORS, no proxy rules and no host allow-list.
set -euo pipefail

cd "$(dirname "$0")/.."
PORT="${PORT:-5173}"
HOST="${HOST:-0.0.0.0}"

if [ ! -f frontend/dist/index.html ]; then
  echo "No frontend build found, building it now ..."
  (cd frontend && npm run build)
fi

# Free the port if something is already on it. Matching on the listening socket
# rather than on a command-line pattern, because a pattern broad enough to catch
# the server also catches the shell that is running this script.
PIDS="$(ss -ltnp 2>/dev/null | grep ":${PORT} " | grep -oP 'pid=\K[0-9]+' | sort -u || true)"
if [ -n "$PIDS" ]; then
  echo "Port ${PORT} is in use by PID(s) ${PIDS}; stopping them."
  # shellcheck disable=SC2086
  kill $PIDS 2>/dev/null || true
  sleep 2
fi

echo "Serving on http://${HOST}:${PORT}  (app at /, API at /api/v1, docs at /docs)"
exec .venv/bin/python -m uvicorn app.main:app --app-dir backend --host "$HOST" --port "$PORT"
