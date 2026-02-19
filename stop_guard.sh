#!/bin/bash
# Stop the vram_guard process

echo "Stopping VRAM Shield..."

# Find the PID of the python process running vram_guard.py
PIDS=$(pgrep -f "python3.*vram_guard.py")

if [ -z "$PIDS" ]; then
    echo "VRAM Shield is not running."
else
    echo "Found VRAM Shield processes: $PIDS"
    # Try SIGTERM first (graceful stop)
    sudo kill -15 $PIDS
    echo "Sent stop signal."
    
    # Wait a moment to see if it stopped
    sleep 2
    if pgrep -f "python3.*vram_guard.py" > /dev/null; then
        echo "Process still running, forcing kill..."
        sudo kill -9 $PIDS
        echo "Process killed."
    else
        echo "Stopped successfully."
    fi
fi
