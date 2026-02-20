#!/bin/bash
# Wrapper to run vram_guard.py using the virtual environment

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Build path to the virtual environment and python script
VENV_DIR="$DIR/../venv"
SCRIPT_PATH="$DIR/../src/vram_guard.py"
if [ ! -d "$VENV_DIR" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv "$VENV_DIR"
    "$VENV_DIR/bin/pip" install nvidia-ml-py psutil PyYAML python-dotenv
fi

# Ensure no other instances are running
if [ -f "$DIR/../.vram_guard.pid" ] || pgrep -f "python3.*vram_guard.py" > /dev/null; then
    echo "Stopping existing VRAM Shield process..."
    "$DIR/stop_guard.sh"
    sleep 1
fi

# Run the script
# If --background is passed, run in background and redirect to log
if [[ "$*" == *"--background"* ]]; then
    echo "Starting VRAM Shield in background... logs at $DIR/../output.log"
    nohup "$VENV_DIR/bin/python3" -u "$SCRIPT_PATH" >> "$DIR/../output.log" 2>&1 &
else
    # Run in foreground
    "$VENV_DIR/bin/python3" -u "$SCRIPT_PATH"
fi
