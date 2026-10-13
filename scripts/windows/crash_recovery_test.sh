#!/usr/bin/env bash
# Live crash-recovery experiment (read-only): run gateway, hard-kill it, wait, restart, hard-kill, restart, stop; then compare the
# union of captured sessions with MT5 history. Usage: bash scripts/windows/crash_recovery_test.sh
set -u
cd "$(dirname "$0")/../.."
kill_gw() { for pid in $(netstat -ano | grep ':8765 .*LISTENING' | awk '{print $5}' | sort -u); do taskkill //PID $pid //F >/dev/null 2>&1; done; }
start_gw() { (powershell -NoProfile -File scripts/windows/run_gateway.ps1 >/dev/null 2>&1 &); }
kill_gw; sleep 2
echo "[1] start"; start_gw; sleep 45
echo "[2] HARD KILL #1 (unflushed buffer lost)"; kill_gw; echo "    downtime 60s"; sleep 60
echo "[3] restart"; start_gw; sleep 40
echo "[4] HARD KILL #2"; kill_gw; sleep 20
echo "[5] restart and run, then graceful end"; start_gw; sleep 40
curl -s localhost:8765/api/health | .venv/Scripts/python.exe -c "import sys,json;h=json.load(sys.stdin);print('health',h['connection'],h['detail']['gaps'])"
kill_gw; sleep 8
