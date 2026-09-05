#!/usr/bin/env python3
"""
VRAM Shield — Real-Time Crash Monitor
=====================================

Scrive su file CSV, ad ogni intervallo, i parametri vitali della macchina:
- GPU temperature, power, utilization, memory
- System memory used/available/total
- OOM-kill count (from /proc/vmstat)
- Top GPU consumer PID and name
- Active alert flags (near thermal limit, near OOM, etc.)

Uso:
    python3 monitor_crash.py              # default 1Hz, auto-named output
    python3 monitor_crash.py --hz 0.5     # 2 campioni/sec
    python3 monitor_crash.py --out FILE   # scrivi su file specifico
    python3 monitor_crash.py --max-mb N   # alert se mem used > N MB

Se la macchina crasha, il file CSV sopravvive sul disco e contiene
i valori fino all'istante prima del crash. Permette diagnosi post-mortem
di OOM, thermal shutdown, o driver hang.

Output: outputs/monitor_YYYYMMDD_HHMMSS.csv  (auto-creato)
"""

import argparse
import csv
import os
import signal
import subprocess
import sys
import time
from datetime import datetime

try:
    import psutil
except ImportError:
    print("FATAL: psutil not installed. pip install psutil")
    sys.exit(1)

try:
    import pynvml
except ImportError:
    print("FATAL: pynvml not installed. pip install nvidia-ml-py")
    sys.exit(1)


# Default thresholds (used only for alert flags in CSV; do NOT change shield behavior)
THERMAL_WARN_C = 85       # GB10 throttle starts here
THERMAL_CRIT_C = 93       # GB10 emergency shutdown zone
MEM_WARN_PCT = 90         # 90% of total system memory used
MEM_CRIT_PCT = 95         # 95% of total system memory used (near OOM)


def read_vmstat_oom_kills():
    """Read total OOM-kill count from /proc/vmstat. Returns int or -1 on error."""
    try:
        with open("/proc/vmstat", "r") as f:
            for line in f:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except (IOError, ValueError):
        pass
    return -1


def read_nvidia_smi_csv():
    """Run nvidia-smi once and parse the output. Returns dict or None on error."""
    try:
        out = subprocess.check_output(
            [
                "nvidia-smi",
                "--query-gpu=index,temperature.gpu,power.draw,utilization.gpu,"
                "utilization.memory,memory.used,memory.free,clocks.current.graphics,"
                "clocks.current.memory,clocks.current.sm",
                "--format=csv,noheader,nounits",
            ],
            stderr=subprocess.DEVNULL,
            timeout=2.0,
        )
        # Parse first line (single-GPU)
        line = out.decode("utf-8", errors="replace").strip().splitlines()[0]
        parts = [p.strip() for p in line.split(",")]
        return {
            "gpu_index": parts[0],
            "gpu_temp_c": parts[1],
            "gpu_power_w": parts[2],
            "gpu_util_pct": parts[3],
            "gpu_mem_util_pct": parts[4],
            "gpu_mem_used_mib": parts[5],
            "gpu_mem_free_mib": parts[6],
            "gpu_clock_graphics_mhz": parts[7],
            "gpu_clock_memory_mhz": parts[8],
            "gpu_clock_sm_mhz": parts[9],
        }
    except Exception:
        return None


def get_top_gpu_consumer():
    """Use pynvml to find the largest compute process. Returns (pid, name, used_mb)."""
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        if not procs:
            return (-1, "none", 0)
        top = max(procs, key=lambda p: p.usedGpuMemory or 0)
        used_mb = (top.usedGpuMemory or 0) / (1024 * 1024)
        name = "unknown"
        try:
            name = psutil.Process(top.pid).name()
        except Exception:
            pass
        return (top.pid, name, used_mb)
    except Exception:
        return (-1, "err", 0)


def main():
    parser = argparse.ArgumentParser(description="Real-time crash monitor for VRAM Shield tests")
    parser.add_argument("--hz", type=float, default=1.0, help="Sample rate (Hz, default 1.0)")
    parser.add_argument("--out", type=str, default=None, help="Output CSV path (auto-named if omitted)")
    parser.add_argument("--max-mb", type=int, default=None, help="Add custom alert column 'mem_over_max' (1 if sys_used_mb > max-mb)")
    args = parser.parse_args()

    interval = 1.0 / max(args.hz, 0.1)

    # Output path
    if args.out:
        out_path = args.out
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # Project root: this file is at tests/monitor_crash.py -> ../outputs/
        out_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "outputs")
        os.makedirs(out_dir, exist_ok=True)
        out_path = os.path.join(out_dir, f"monitor_{ts}.csv")

    # Initialize NVML
    try:
        pynvml.nvmlInit()
    except Exception as e:
        print(f"FATAL: NVML init failed: {e}")
        sys.exit(1)

    # CSV header
    header = [
        "timestamp",
        "epoch_ms",
        "gpu_temp_c",
        "gpu_power_w",
        "gpu_util_pct",
        "gpu_mem_util_pct",
        "gpu_mem_used_mib",
        "gpu_mem_free_mib",
        "gpu_clock_graphics_mhz",
        "gpu_clock_memory_mhz",
        "gpu_clock_sm_mhz",
        "sys_mem_total_mib",
        "sys_mem_used_mib",
        "sys_mem_available_mib",
        "sys_mem_pct",
        "swap_used_mib",
        "oom_kill_total",
        "top_gpu_pid",
        "top_gpu_name",
        "top_gpu_used_mib",
        "alert_thermal",
        "alert_thermal_crit",
        "alert_mem_warn",
        "alert_mem_crit",
    ]
    if args.max_mb:
        header.append("alert_mem_over_max")
    header.append("note")

    f = open(out_path, "w", newline="", buffering=1)  # line-buffered
    writer = csv.writer(f)
    writer.writerow(header)
    print(f"[monitor] Writing to: {out_path}")
    print(f"[monitor] Sample rate: {args.hz} Hz ({interval:.3f}s interval)")
    print(f"[monitor] Press Ctrl+C to stop.")

    # Graceful shutdown
    stop = False
    def _sigint(*_):
        global stop
        stop = True
        print("\n[monitor] Stopping...")
    signal.signal(signal.SIGINT, _sigint)
    signal.signal(signal.SIGTERM, _sigint)

    # Read system memory total once (it doesn't change at runtime)
    try:
        sys_total_mib = psutil.virtual_memory().total / (1024 * 1024)
    except Exception:
        sys_total_mib = 0

    last_oom_kills = -1
    oom_delta_note = ""

    while not stop:
        t0 = time.time()
        now = datetime.now()
        epoch_ms = int(t0 * 1000)

        # NVML via nvidia-smi (gives us power, util, clocks - pynvml lacks these on some)
        nvs = read_nvidia_smi_csv() or {}
        # Top GPU consumer via pynvml
        top_pid, top_name, top_used = get_top_gpu_consumer()

        # System memory
        try:
            vm = psutil.virtual_memory()
            sys_used_mib = vm.used / (1024 * 1024)
            sys_avail_mib = vm.available / (1024 * 1024)
            sys_pct = vm.percent
        except Exception:
            sys_used_mib = sys_avail_mib = sys_pct = 0

        try:
            swap_used_mib = psutil.swap_memory().used / (1024 * 1024)
        except Exception:
            swap_used_mib = 0

        oom_kills = read_vmstat_oom_kills()
        if last_oom_kills >= 0 and oom_kills > last_oom_kills:
            oom_delta_note = f"OOM_KILL_DELTA:+{oom_kills - last_oom_kills}"
        else:
            oom_delta_note = ""
        last_oom_kills = oom_kills

        # Alerts
        try:
            t_c = float(nvs.get("gpu_temp_c", 0))
        except Exception:
            t_c = 0
        alert_thermal = 1 if t_c >= THERMAL_WARN_C else 0
        alert_thermal_crit = 1 if t_c >= THERMAL_CRIT_C else 0
        alert_mem_warn = 1 if sys_pct >= MEM_WARN_PCT else 0
        alert_mem_crit = 1 if sys_pct >= MEM_CRIT_PCT else 0
        if args.max_mb:
            alert_mem_over_max = 1 if sys_used_mib > args.max_mb else 0
        else:
            alert_mem_over_max = ""

        row = [
            now.strftime("%Y-%m-%d %H:%M:%S.%f")[:-3],
            epoch_ms,
            nvs.get("gpu_temp_c", ""),
            nvs.get("gpu_power_w", ""),
            nvs.get("gpu_util_pct", ""),
            nvs.get("gpu_mem_util_pct", ""),
            nvs.get("gpu_mem_used_mib", ""),
            nvs.get("gpu_mem_free_mib", ""),
            nvs.get("gpu_clock_graphics_mhz", ""),
            nvs.get("gpu_clock_memory_mhz", ""),
            nvs.get("gpu_clock_sm_mhz", ""),
            f"{sys_total_mib:.0f}",
            f"{sys_used_mib:.0f}",
            f"{sys_avail_mib:.0f}",
            f"{sys_pct:.1f}",
            f"{swap_used_mib:.0f}",
            oom_kills,
            top_pid,
            top_name,
            f"{top_used:.0f}",
            alert_thermal,
            alert_thermal_crit,
            alert_mem_warn,
            alert_mem_crit,
        ]
        if args.max_mb:
            row.append(alert_mem_over_max)
        row.append(oom_delta_note)

        try:
            writer.writerow(row)
        except Exception as e:
            print(f"[monitor] Write error: {e}")
            break

        # Sleep until next sample
        elapsed = time.time() - t0
        sleep_for = interval - elapsed
        if sleep_for > 0:
            time.sleep(sleep_for)

    f.close()
    pynvml.nvmlShutdown()
    print(f"[monitor] Stopped. CSV: {out_path}")


if __name__ == "__main__":
    main()
