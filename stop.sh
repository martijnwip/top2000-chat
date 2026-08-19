#!/usr/bin/env bash
# Stopt backend en frontend die met start.sh zijn gestart.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

RUN_DIR=".run"

stop_pid() {
    local naam="$1" pidfile="$2"
    if [ ! -f "$pidfile" ]; then
        echo "$naam: geen PID-bestand, waarschijnlijk niet gestart via start.sh"
        return
    fi
    local pid
    pid="$(cat "$pidfile")"
    if kill -0 "$pid" 2>/dev/null; then
        # Negatief PID doodt de hele process group (npm + het vite-kindproces).
        kill -- "-$pid" 2>/dev/null || kill "$pid" 2>/dev/null
        echo "$naam gestopt (PID $pid)"
    else
        echo "$naam draaide niet meer (PID $pid)"
    fi
    rm -f "$pidfile"
}

stop_pid "Backend" "$RUN_DIR/backend.pid"
stop_pid "Frontend" "$RUN_DIR/frontend.pid"
