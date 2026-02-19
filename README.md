# VRAM Shield

**VRAM Shield** is a lightweight Python tool designed to monitor and protect NVIDIA GPU memory usage. It is particularly optimized for the **NVIDIA GB10 Grace Blackwell** superchip (and other Unified Memory architectures), where traditional VRAM monitoring tools may fail or report misleading global statistics.

## Features

- **Real-time Monitoring**: Tracks GPU memory usage per process.
- **Automated Protection**: Automatically terminates processes that exceed a user-defined memory threshold.
- **Grace Blackwell Support**: Handles Unified Memory architectures where global VRAM metrics are often "Not Supported" or shared with system RAM.
- **Safety First**: Includes a "Dry Run" mode to simulate behavior without killing processes.
- **Whitelist**: Prevents critical system processes (e.g., `Xorg`, `gnome-shell`) from being terminated.

## Installation

This project uses a virtual environment to manage dependencies safely.

1.  **Clone the repository** (if you haven't already):
    ```bash
    git clone <your-repo-url>
    cd VRAM_shield
    ```

2.  **Run the wrapper script**:
    The included `run_guard.sh` script will automatically set up the virtual environment and install dependencies (`nvidia-ml-py`) on the first run.

## Usage

You can use the `run_guard.sh` wrapper to execute the monitor.

### 1. Dry Run (Test Mode)
Use this to see which processes *would* be killed without actually terminating them. This is highly recommended for your first run.

```bash
./run_guard.sh --threshold 40000 --dry-run
```
*Monitors for processes using more than 40,000 MB (40 GB).*

### 2. Active Protection Mode
To actively protect your system and kill offending processes, run with `sudo` (required to terminate other users' processes) and remove the `--dry-run` flag.

```bash
sudo ./run_guard.sh --threshold 80000
```
*Terminates any process using more than 80,000 MB (80 GB).*

### 3. Stopping the Monitor
To stop the VRAM Shield, you can simply press `Ctrl+C` if it's running in your terminal.

If you ran it in the background (e.g., with `&` or via a service), use the included helper script:
```bash
sudo ./stop_guard.sh
```

### Options

| Flag | Description | Default |
| :--- | :--- | :--- |
| `--threshold <MB>` | **Required**. The memory limit in Megabytes. | N/A |
| `--mode <MODE>` | `process` (limit per process) or `total` (limit total system VRAM). | `process` |
| `--interval <SEC>` | Monitoring interval in seconds. | `1.0` |
| `--dry-run` | Monitor only; do not kill processes. | `False` |
| `--gpu <ID>` | GPU index to monitor. | `0` |
| `--whitelist <NAMES>` | List of process names to ignore. | `Xorg gnome-shell` |

## Protection Modes

### Process Mode (Default)
`--mode process`
Terminates any *single process* that exceeds the threshold.
- **Best for:** Preventing one runaway script from eating all memory.
- **Example:** "Kill any script larger than 40GB."

### Total Mode (Recommended for GB10)
`--mode total`
Terminates the largest non-whitelisted process if the *sum of all processes* exceeds the threshold.
- **Best for:** Preventing System OOM (Out of Memory) crashes on Unified Memory systems.
- **Example:** "If total VRAM usage > 110GB, kill the biggest job to save the system."

## Why is this needed for GB10 (Grace Blackwell)?

The NVIDIA GB10 chip uses **Unified Memory**, sharing 128GB of LPDDR5X between the ARM CPU and the Blackwell GPU. 

- **Standard Tools Fail**: Traditional tools like `nvidia-smi` often report "Not Supported" for global VRAM usage because there is no distinct "Video RAM" capacity—it's all system memory.
- **OOM Danger**: If a process consumes all available memory, the Linux kernel's OOM (Out of Memory) killer will indiscriminately terminate processes to save the system, which can crash your desktop or critical services.
- **VRAM Shield Solution**: This tool calculates VRAM usage by summing up the memory allocated by individual GPU processes, providing a reliable metric even when global stats are unavailable. It allows you to set a "safety buffer" (e.g., kill at 110GB) to prevent a full system OOM crash.

## Requirements

- Python 3
- NVIDIA Drivers
- `nvidia-ml-py` (installed automatically by the wrapper script)
