#!/bin/bash
# Check the status of VRAM Shield

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_FILE="$DIR/../output.log"
PID_FILE="$DIR/../.vram_guard.pid"

# Try to get PID from pid file
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    # Check if the process is actually running
    if ! ps -p "$PID" > /dev/null; then
        PID="" # Process is dead, pid file is stale
    fi
else
    PID=""
fi

# Fallback to pgrep
if [ -z "$PID" ]; then
    PIDS=$(pgrep -f "python3.*vram_guard.py")
else
    PIDS="$PID"
fi

if [ -z "$PIDS" ]; then
    echo -e "\e[31mVRAM Shield is NOT running.\e[0m"
else
    echo -e "\e[32mVRAM Shield is RUNNING.\e[0m"
    for pid in $PIDS; do
        # Get the full command line
        CMDLINE=$(ps -p $pid -o args=)
        START_TIME=$(ps -p $pid -o lstart=)
        echo "--------------------------------------------------"
        echo "PID: $pid"
        echo "Started: $START_TIME"
        echo "Command: $CMDLINE"
    done
    
    if [ -f "$LOG_FILE" ]; then
        echo "--------------------------------------------------"
        echo "Last 5 lines of log ($LOG_FILE):"
        tail -n 5 "$LOG_FILE"
    fi
fi
