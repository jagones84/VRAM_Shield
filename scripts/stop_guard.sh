#!/bin/bash
# Stop the vram_guard process

echo "Stopping VRAM Shield..."

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PID_FILE="$DIR/../.vram_guard.pid"

# Try to read the PID from the file first
if [ -f "$PID_FILE" ]; then
    PIDS=$(cat "$PID_FILE")
    # Verify the PID belongs to vram_guard before adding to list
    if ! ps -p "$PIDS" -o args= | grep -q "vram_guard.py"; then
        PIDS=""
    fi
else
    PIDS=""
fi

# Fallback: Find the PID using pgrep if not found via pid file
if [ -z "$PIDS" ]; then
    PIDS=$(pgrep -f "python3.*vram_guard.py")
fi

if [ -z "$PIDS" ]; then
    echo "VRAM Shield is not running."
    rm -f "$PID_FILE" # Clean up dead pid file if it exists
else
    echo "Found VRAM Shield processes: $PIDS"
    # Try SIGTERM first (graceful stop)
    kill -15 $PIDS
    echo "Sent stop signal."
    
    # Wait a moment to see if it stopped
    sleep 2
    if pgrep -f "python3.*vram_guard.py" > /dev/null; then
        echo "Process still running, forcing kill..."
        kill -9 $PIDS
        echo "Process killed."
    else
        echo "Stopped successfully."
    fi
    rm -f "$PID_FILE"
fi
