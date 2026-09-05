#!/usr/bin/env bash
# VRAM Shield — Run full stress test (monitor + gpu_stress)
# Usage: ./scripts/run_stress_test.sh <MB> [seconds] [hz]
#   MB      : megabytes to allocate on GPU (e.g. 105000 = 105 GB)
#   seconds : test duration in seconds (default 1200 = 20 min)
#   hz      : monitor sample rate (default 2)
#
# Example: ./scripts/run_stress_test.sh 105000 1200 2
#
# Questo script:
#   1. FERMA il guard (altrimenti trigger appena sale la memoria)
#   2. Avvia monitor_realtime.py in background (scrive outputs/monitor_*.csv)
#   3. Avvia gpu_stress in background (alloca MB + compute sustained)
#   4. Aspetta seconds, poi killa tutto
#   5. Stampa path del CSV finale per analisi
#
# Replicare il test originale: ./scripts/run_stress_test.sh 105000 1200 1

set -e

REPO_DIR="${REPO_DIR:-/home/jagones/Programs/VRAM_shield}"
MB="${1:-105000}"
SECONDS="${2:-1200}"
HZ="${3:-2}"

cd "$REPO_DIR"

echo "[run_stress_test] MB=$MB, duration=${SECONDS}s, monitor_hz=$HZ"

# 1. Ferma il guard (cosi' non triggera durante il test)
echo "[run_stress_test] stopping guard (if running)..."
pkill -f "vram_guard" 2>/dev/null || true
sleep 2

# 2. Determina path del CSV monitor (auto-naming)
TS=$(date +%Y%m%d_%H%M%S)
MONITOR_CSV="$REPO_DIR/outputs/monitor_${TS}.csv"
STRESS_LOG="/tmp/gpu_stress_${TS}.log"
MONITOR_LOG="/tmp/monitor_${TS}.log"

# 3. Avvia monitor in background
echo "[run_stress_test] starting monitor -> $MONITOR_CSV"
nohup ./venv/bin/python3 -u scripts/monitor_realtime.py \
    --hz "$HZ" \
    --out "$MONITOR_CSV" \
    > "$MONITOR_LOG" 2>&1 &
MON_PID=$!
disown

# 4. Avvia gpu_stress in background
echo "[run_stress_test] starting gpu_stress ${MB}MB for ${SECONDS}s"
nohup ./tests/gpu_stress "$MB" "$SECONDS" > "$STRESS_LOG" 2>&1 &
STRESS_PID=$!
disown

# 5. Stata dei processi
echo "[run_stress_test] monitor_pid=$MON_PID  stress_pid=$STRESS_PID"
echo "[run_stress_test] monitor_csv=$MONITOR_CSV"
echo "[run_stress_test] monitor_log=$MONITOR_LOG"
echo "[run_stress_test] stress_log=$STRESS_LOG"
echo

# 6. Aspetta che gpu_stress finisca (o timeout se si blocca)
echo "[run_stress_test] waiting for stress test to complete (max ${SECONDS}s + 30s)..."
WAITED=0
MAX_WAIT=$((SECONDS + 30))
while kill -0 "$STRESS_PID" 2>/dev/null; do
    if [ $WAITED -ge $MAX_WAIT ]; then
        echo "[run_stress_test] timeout reached, killing..."
        kill -9 "$STRESS_PID" 2>/dev/null || true
        break
    fi
    sleep 10
    WAITED=$((WAITED + 10))
done

# 7. Killa monitor (il monitor non ha auto-stop duration; lo fermiamo ora)
sleep 3
kill -INT "$MON_PID" 2>/dev/null || true
sleep 2

# 8. Stat finali
echo
echo "=== TEST RESULTS ==="
echo "monitor_csv: $MONITOR_CSV"
if [ -f "$MONITOR_CSV" ]; then
    LINES=$(wc -l < "$MONITOR_CSV")
    echo "monitor rows: $((LINES - 1))"
fi
if [ -f "$STRESS_LOG" ]; then
    echo "--- stress log tail ---"
    tail -10 "$STRESS_LOG"
fi

# 9. Riavvia guard (opzionale, commentato per non far partire se non richiesto)
# echo "[run_stress_test] restarting guard..."
# ./scripts/run_guard.sh
echo
echo "[run_stress_test] DONE. To analyze: cat $MONITOR_CSV | head -1 && tail -3 $MONITOR_CSV"
