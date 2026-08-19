#!/usr/bin/env bash
# Start backend (FastAPI/uvicorn) en frontend (Vite) samen.
# PID's en logs gaan naar .run/, zodat stop.sh ze kan vinden.
#
# --demo: opent de browser met een voorbeeldgesprek van drie vragen alvast
# ingevuld (echte antwoorden van de lokale backend, geen nepdata — zie de
# "demo"-URL-parameter en DEMO_VRAGEN in frontend/src/App.jsx).
set -euo pipefail
set -m  # eigen process group per achtergrondjob, zodat stop.sh ook npm's vite-kindproces meekrijgt
cd "$(dirname "${BASH_SOURCE[0]}")"

DEMO=0
if [ "${1:-}" = "--demo" ]; then
    DEMO=1
fi

RUN_DIR=".run"
mkdir -p "$RUN_DIR"

if [ -f "$RUN_DIR/backend.pid" ] && kill -0 "$(cat "$RUN_DIR/backend.pid")" 2>/dev/null; then
    echo "Backend draait al (PID $(cat "$RUN_DIR/backend.pid"))"
else
    .venv/bin/uvicorn backend.app:app --reload --port 8000 > "$RUN_DIR/backend.log" 2>&1 &
    echo $! > "$RUN_DIR/backend.pid"
    echo "Backend gestart (PID $!) — logs in $RUN_DIR/backend.log"
fi

if [ -f "$RUN_DIR/frontend.pid" ] && kill -0 "$(cat "$RUN_DIR/frontend.pid")" 2>/dev/null; then
    echo "Frontend draait al (PID $(cat "$RUN_DIR/frontend.pid"))"
else
    (cd frontend && npm run dev) > "$RUN_DIR/frontend.log" 2>&1 &
    echo $! > "$RUN_DIR/frontend.pid"
    echo "Frontend gestart (PID $!) — logs in $RUN_DIR/frontend.log"
fi

if [ "$DEMO" = "1" ]; then
    echo "Demo-modus: wachten tot frontend reageert..."
    for i in $(seq 1 30); do
        curl -sf http://localhost:5173/ > /dev/null && break
        sleep 1
    done
    open "http://localhost:5173/?demo=1" 2>/dev/null \
        || echo "Kon browser niet automatisch openen — ga naar http://localhost:5173/?demo=1"
fi

echo "Backend:  http://localhost:8000"
echo "Frontend: http://localhost:5173"
echo "Stoppen met: ./stop.sh"
echo "Voorbeeldgesprek: ./start.sh --demo"
