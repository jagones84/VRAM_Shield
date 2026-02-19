# VRAM Shield

**VRAM Shield** is a lightweight Python tool designed to monitor and protect NVIDIA GPU memory usage. It is particularly optimized for the **NVIDIA GB10 Grace Blackwell** superchip (and other Unified Memory architectures), where traditional VRAM monitoring tools may fail or report misleading global statistics.

## Features

- **Real-time Monitoring**: Tracks GPU memory usage per process.
- **Aggressive Out-of-Memory (OOM) Protection**: Automatically and instantly terminates processes (with `SIGKILL`) that exceed a user-defined memory threshold, preventing total system lockups on Unified Memory platforms.
- **Grace Blackwell Support**: Calculates RSS System Memory footprint when NVIDIA NVML drivers report 0 MB usage for compute processes in Unified Memory.
- **Auto-Startup Service**: Can be installed as a SystemD background daemon that protects your hardware continuously on boot.
- **Configuration File**: Easy-to-manage `config.yaml` with adjustable thresholds and whitelist capabilities.

## Installation

This project uses a virtual environment to manage dependencies safely.

1. **Clone the repository**:

    ```bash
    git clone https://github.com/your-username/VRAM_shield.git
    cd VRAM_shield
    ```

2. **Configure the Shield**:
    Open `config/config.yaml` to set your desired memory limits.
    The default threshold is **126,000 MB (126 GB)**.

    ```yaml
    threshold: 126000
    interval: 1.0
    gpu_index: 0
    dry_run: false
    whitelist_pids:
      - 1
    mode: "PROCESS"
    ```

3. **Install as a SystemD Service (Recommended)**:
    For continuous background protection running on startup:

    ```bash
    sudo ./scripts/install_service.sh
    ```

    *Check status after installation via `systemctl status vram_guard`.*

## Manual Usage (Without SystemD)

You can use the provided wrapper scripts to control the monitor manually. Dependencies (`nvidia-ml-py`, `psutil`, `PyYAML`, `python-dotenv`) are installed automatically on the first run.

### 1. Start the Monitor

```bash
# Run in the foreground:
./scripts/run_guard.sh

# Or, run in the background (logs to vram_guard.log):
./scripts/run_guard.sh --background
```

*Note: VRAM Shield guarantees that only 1 instance can run at a time. Launching it again will automatically stop the old instance.*

### 2. Checking Status

To check if the VRAM Shield is running and view its logs, run:

```bash
./scripts/status_guard.sh
```

### 3. Stopping the Monitor

To stop the VRAM Shield gracefully:

```bash
./scripts/stop_guard.sh
```

## Why is this needed for GB10 (Grace Blackwell)?

The NVIDIA GB10 chip uses **Unified Memory**, sharing 128GB of LPDDR5X between the ARM CPU and the Blackwell GPU.

- **Standard Tools Fail**: Traditional tools like `nvidia-smi` often report "Not Supported" for global VRAM usage because there is no distinct "Video RAM" capacity. Furthermore, compute tasks may appear to allocate `0 MB` of GPU memory.
- **OOM Danger**: If a process consumes all available memory, the Linux kernel's OOM (Out of Memory) killer will indiscriminately terminate processes to save the system, which can crash your desktop or critical services.
- **VRAM Shield Solution**: This tool calculates process memory usage using fallback OS mechanisms (RSS footprint) when NVML fails, providing a reliable metric. It allows you to set a "safety buffer" (e.g., kill at 126GB) to forcefully prevent a full system OOM crash.

## Folder Structure

- `src/vram_guard.py` - Main execution loop and monitoring logic.
- `scripts/` - Bash wrappers for starting, stopping, checking status, and installing the system service.
- `config/config.yaml` - User configuration.
- `venv/` - (Auto-generated) Isolated Python environment.

## Requirements

- Python 3
- NVIDIA Drivers Supported by `pynvml`
