#!/bin/bash
# Test script: launch gpu-burn, measure VRAM at T+5, T+10, T+15, then cleanup.
# Usage: ./vram_test.sh [MB] [DURATION_SECS]
set -e
MB="${1:-90000}"
DUR="${2:-30}"

echo "=== Step 1: baseline (no load) ==="
/home/jagones/Programs/VRAM_shield/venv/bin/python /home/jagones/Programs/VRAM_shield/tests/vram_measure.py baseline

echo ""
echo "=== Step 2: launch gpu-burn ${MB}MB for ${DUR}s ==="
setsid nohup /home/jagones/gpu-burn/gpu-burn/gpu_burn -m "$MB" "$DUR" > /tmp/burn_vram_test.log 2>&1 < /dev/null &
BURN_PID=$!
disown
echo "gpu-burn PID=$BURN_PID"
sleep 1
ps -p $BURN_PID -o pid,pcpu,rss,vsz,etime,cmd 2>&1 | head -2

for t in 5 10 15; do
    sleep $((t == 5 ? 5 : 5))
    echo ""
    echo "=== Step 3.${t}: measurement at T+${t}s ==="
    /home/jagones/Programs/VRAM_shield/venv/bin/python /home/jagones/Programs/VRAM_shield/tests/vram_measure.py under_load_T${t}
done

echo ""
echo "=== Step 4: wait for burn to finish ==="
wait $BURN_PID 2>/dev/null || true
echo "gpu-burn exit: $?"

echo ""
echo "=== Step 5: final state (no load) ==="
/home/jagones/Programs/VRAM_shield/venv/bin/python /home/jagones/Programs/VRAM_shield/tests/vram_measure.py final

echo ""
echo "=== Step 6: burn log tail ==="
tail -10 /tmp/burn_vram_test.log
