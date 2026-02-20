# 🛡️ VRAM Shield

**VRAM Shield** is a lightweight, high-performance Python tool designed to monitor and protect NVIDIA GPU memory usage. It is specifically optimized for **Unified Memory Architectures** (like NVIDIA Grace Hopper/Blackwell), where traditional VRAM monitoring can be misleading.

It acts as a watchdog, automatically terminating processes that exceed safe memory thresholds to prevent system lockups or OOM (Out-of-Memory) crashes.

---

## ✨ Features

- **🚀 Unified Memory Support**: Intelligent handling of System RAM + VRAM accounting for Grace Hopper/Blackwell chips.
- **⚡ Zero-Latency Protection**: Instantly terminates (`SIGKILL`) processes exceeding defined thresholds.
- **🧠 Dynamic Baseline Calibration**: Automatically detects and offsets system-reserved memory for precise triggering.
- **🔄 Systemd Integration**: Runs as a persistent user service with auto-restart capabilities.
- **📊 Real-time Status**: Simple CLI tools to check status and logs.

---

## 🛠️ Installation

### 1. Clone the Repository
```bash
git clone https://github.com/your-username/VRAM_shield.git
cd VRAM_shield
```

### 2. Run the Installer
The included script sets up the virtual environment and installs dependencies automatically.
```bash
./scripts/run_guard.sh
```
*(The first run will take a moment to set up `venv`)*

---

## ⚙️ Configuration

Edit `config/config.yaml` to customize behavior.

```yaml
threshold: 35000       # Memory limit in MB (e.g., 35 GB)
mode: "SYSTEM"         # "SYSTEM" (Total Memory) or "PROCESS" (Per-Process)
interval: 0.1          # Monitoring frequency in seconds
autostart: true        # Enable auto-start on boot
whitelist_pids:        # PIDs to ignore (e.g., system processes)
  - 1
```

---

## 🖥️ Usage

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

## 🧪 Testing & Verification

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

## 🔧 Systemd Service (Auto-Start)

The Shield is designed to run as a **Systemd User Service**.

- **Enable/Start**: `systemctl --user enable --now vram_guard.service`
- **Check Logs**: `journalctl --user -u vram_guard -f`
- **Restart**: `systemctl --user restart vram_guard.service`

*Note: The `run_guard.sh` script handles this automatically for you.*
