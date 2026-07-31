# VRAM Shield

**VRAM Shield** is a lightweight, high-performance Python tool designed to monitor and protect NVIDIA GPU memory usage. It is specifically optimized for **Unified Memory Architectures** (like NVIDIA Grace Hopper/Blackwell), where traditional VRAM monitoring can be misleading.

It acts as a watchdog, automatically terminating processes that exceed safe memory thresholds to prevent system lockups or OOM (Out-of-Memory) crashes.

---

## Features

- Unified Memory support (system RAM fallback trigger when NVML totals are not supported)
- Fast kill path (SIGKILL on Linux, SIGTERM on Windows)
- Dynamic baseline calibration for unified memory platforms
- systemd user service autostart on Linux
- CLI scripts for start/stop/status

---

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/jagones84/VRAM_Shield.git
cd VRAM_Shield
```

### 2. Run the Installer
The included script sets up the virtual environment and installs dependencies automatically.
```bash
./scripts/run_guard.sh
```
*(The first run will take a moment to set up `venv`)*

---

## Configuration

Edit `config/config.yaml` to customize behavior.

To keep machine-specific settings out of git, put overrides in `config/config.local.yaml` (it is loaded automatically if present).

```yaml
threshold: 126000
interval: 1.0
gpu_index: 0
dry_run: false
mode: "PROCESS"
autostart: false
whitelist_pids: []
```

---

## Usage

### Start / Restart
```bash
./scripts/run_guard.sh
```
*Starts the shield. If configured, it also enables the Systemd service.*

### Check Status
```bash
./scripts/status_guard.sh
```
*Shows if the shield is **ACTIVE (PROTECTED)** or **STOPPED**, along with recent logs.*

### Stop
```bash
./scripts/stop_guard.sh
```
*Stops the background process and disables the auto-restart service.*

---

## Testing & Verification

To verify the Shield's functionality, we recommend using **gpu-burn** to generate artificial VRAM load.

### 1. Install `gpu-burn`
If you don't have it already, clone and build the standard benchmarking tool:

```bash
git clone https://github.com/wilicc/gpu-burn.git
cd gpu-burn
make
```
*(Requires CUDA Toolkit to be installed)*

### 2. Run a Verification Test
We provide scripts to safely test the trigger threshold without crashing your system.

**Ramp-Up Test (Recommended):**
This script incrementally loads VRAM to pinpoint exactly when the Shield triggers.

```bash
# Run using the project's virtual environment
./venv/bin/python3 tests/ramp_up_test.py
```

**Manual Load Test:**
You can also run `gpu-burn` directly with a specific memory target to test the limit:

```bash
# Example: Load 27 GB (should trigger if threshold is 25 GB)
./gpu_burn 27000
```

---

## Systemd Service (Auto-Start)

The Shield is designed to run as a **Systemd User Service**.

- **Enable/Start**: `systemctl --user enable --now vram_guard.service`
- **Check Logs**: `journalctl --user -u vram_guard -f`
- **Restart**: `systemctl --user restart vram_guard.service`

*Note: The `run_guard.sh` script handles this automatically for you.*

## Security & privacy

- `.env` / `.env.*` are ignored by git (except `.env.example`)
- `venv/`, logs (`*.log`) and PID files (`*.pid`) are ignored by git
- `calibration_report*.txt` is ignored by git (machine-specific output)

Before pushing, verify with:

```bash
git status
git ls-files
```
