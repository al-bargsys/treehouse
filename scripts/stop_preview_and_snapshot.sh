#!/bin/bash
# Stop both preview and snapshot servers started by start_preview_and_snapshot.sh

set -e

kill_pid_file () {
  local f="$1"
  if [ -f "$f" ]; then
    local pid
    pid=$(cat "$f" 2>/dev/null || true)
    if [ -n "$pid" ]; then
      kill "$pid" 2>/dev/null || true
    fi
    rm -f "$f"
  fi
}

kill_pid_file /tmp/camera_proxy.pid
kill_pid_file /tmp/preview_mjpeg.pid
kill_pid_file /tmp/snapshot_server.pid

# Also kill anything still listening on the default ports (best-effort)
for P in 8082 8083 8084; do
  if lsof -Pi :${P} -sTCP:LISTEN -t >/dev/null 2>&1 ; then
    PIDS=$(lsof -Pi :${P} -sTCP:LISTEN -t 2>/dev/null || true)
    if [ -n "$PIDS" ]; then
      echo "Killing processes on port ${P}: ${PIDS}"
      kill $PIDS 2>/dev/null || true
      sleep 0.5
    fi
  fi
done

echo "Stopped preview and snapshot servers (if running)."


