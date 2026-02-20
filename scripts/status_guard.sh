#!/bin/bash
# Check the status of VRAM Shield

# Determine if running via Systemd Service
IS_SERVICE_ACTIVE=false
if command -v systemctl >/dev/null 2>&1; then
    if systemctl --user is-active --quiet vram_guard.service; then
        IS_SERVICE_ACTIVE=true
    fi
fi

# Check if the actual Python process is running
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_FILE="$DIR/../output.log"
PIDS=$(pgrep -f "python3.*vram_guard.py")

if [ -n "$PIDS" ]; then
    # PROCESS IS RUNNING -> PROTECTED
    echo -e "\e[32m==================================================\e[0m"
    echo -e "\e[32m   STATUS: VRAM SHIELD IS ACTIVE (PROTECTED)      \e[0m"
    echo -e "\e[32m==================================================\e[0m"
    
    # Optional: Info about how it's running (Service vs Manual)
    if [ "$IS_SERVICE_ACTIVE" = true ]; then
         echo "Mode: Systemd Service (Auto-Start Enabled)"
    else
         echo "Mode: Manual Process (Warning: Might not auto-restart)"
    fi

    for pid in $PIDS; do
        START_TIME=$(ps -p $pid -o lstart=)
        echo "PID: $pid | Started: $START_TIME"
    done
    
    # Show config snapshot
    if [ -f "$LOG_FILE" ]; then
        echo "--------------------------------------------------"
        echo "Latest Log Activity:"
        tail -n 3 "$LOG_FILE"
    fi
    exit 0
else
    # PROCESS IS NOT RUNNING -> NOT PROTECTED
    echo -e "\e[31m==================================================\e[0m"
    echo -e "\e[31m   STATUS: VRAM SHIELD IS STOPPED (NOT PROTECTED) \e[0m"
    echo -e "\e[31m==================================================\e[0m"
    
    # Diagnostics
    if [ "$IS_SERVICE_ACTIVE" = true ]; then
        echo -e "\e[33mWARNING: Systemd service is 'active' but the process is dead.\e[0m"
        echo "Action: Run 'systemctl --user restart vram_guard.service' to fix."
    fi
    exit 1
fi
