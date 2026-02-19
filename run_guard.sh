#!/bin/bash
# Wrapper to run vram_guard.py using the virtual environment

# Get the directory of this script
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"

# Check if venv exists
if [ ! -d "$DIR/venv" ]; then
    echo "Virtual environment not found. Creating..."
    python3 -m venv "$DIR/venv"
    "$DIR/venv/bin/pip" install nvidia-ml-py
fi

# Run the script
# Pass all arguments to the python script
"$DIR/venv/bin/python3" "$DIR/vram_guard.py" "$@"
