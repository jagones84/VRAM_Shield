#!/usr/bin/env python3
"""
VRAM Shield — Real-Time Stress Monitor
=====================================
Monitor continuo per test di stress VRAM/GPU. Salva TUTTI i parametri utili
in un CSV auto-nominato `monitor_YYYYMMDD_HHMMSS.csv` dentro `outputs/`.

Colonne CSV:
  GPU     : temp_c, power_w, util_pct, clock_graph_mhz, clock_sm_mhz, alloc_total_mib
  CPU     : max_temp_c, avg_temp_c, avg_freq_mhz, max_freq_mhz, util_pct
  System  : sys_mem_total_mib, sys_mem_used_mib, sys_mem_available_mib, sys_mem_pct
  Derived : dashboard_equiv_mib, dashboard_equiv_gb  (= psutil.used + 8 GB overhead, GB10)
  Events  : oom_kill_total, driver_err_30s
  Top GPU : top_gpu_pid, top_gpu_name, top_gpu_used_mib
  Alerts  : alert_gpu_thermal, alert_cpu_thermal, alert_mem_crit

Usage:
    python3 scripts/monitor_realtime.py                       # 2 Hz, auto-naming
    python3 scripts/monitor_realtime.py --hz 1                # 1 sample/sec
    python3 scripts/monitor_realtime.py --out /tmp/test.csv   # path custom
    python3 scripts/monitor_realtime.py --duration 600        # auto-stop dopo 10 min
"""

import argparse
import csv
import glob
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


THERMAL_WARN_C = 85
THERMAL_CRIT_C = 93
CPU_THERMAL_WARN_C = 85
CPU_THERMAL_CRIT_C = 95
MEM_WARN_PCT = 90
MEM_CRIT_PCT = 95

# GB10 unified memory: nvidia-smi memory.used ritorna N/A.
# Il valore "Dashboard" NVIDIA e' approssimativamente psutil.used + questo scarto
# (8 GB di overhead driver / kernel / CUDA context / page cache).
GB10_DASHBOARD_OVERHEAD_MIB = 8192


def read_cpu_thermal_zones():
    """Legge tutte le zone acpitz. Ritorna (max_c, list_di_c)."""
    zones = []
    for tz in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        tp = os.path.join(tz, "type")
        tval = os.path.join(tz, "temp")
        try:
            with open(tp) as f:
                name = f.read().strip()
        except (IOError, FileNotFoundError):
            continue
        if "acpitz" not in name and "cpu" not in name.lower() and "soc" not in name.lower():
            continue
        try:
            with open(tval) as f:
                millideg = int(f.read().strip())
            zones.append((name, millideg / 1000.0))
        except (IOError, FileNotFoundError, ValueError):
            continue
    if not zones:
        return None, []
    max_c = max(t for _, t in zones)
    return max_c, zones


def read_cpu_freq_mhz():
    """Ritorna (avg_mhz, max_mhz) delle frequenze CPU attuali."""
    freqs = []
    for cpu_dir in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")):
        try:
            with open(cpu_dir) as f:
                khz = int(f.read().strip())
            freqs.append(khz / 1000.0)  # MHz
        except (IOError, FileNotFoundError, ValueError):
            continue
    if not freqs:
        return None, None
    return sum(freqs) / len(freqs), max(freqs)


def read_cpu_util_pct():
    """Sample breve di psutil.cpu_percent. Ritorna % totale."""
    return psutil.cpu_percent(interval=None)


def read_nvidia_smi_csv():
    """Run nvidia-smi once. Returns dict or None on error."""
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
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    line = out.decode("utf-8", errors="replace").strip().splitlines()
    if not line:
        return None
    parts = [p.strip() for p in line[0].split(",")]
    return {
        "temp_c":          _to_float(parts[1]),
        "power_w":         _to_float(parts[2]),
        "util_gpu_pct":    _to_float(parts[3]),
        "util_mem_pct":    _to_float(parts[4]),
        "mem_used_mib":    _to_float(parts[5]),
        "mem_free_mib":    _to_float(parts[6]),
        "clock_graph_mhz": _to_float(parts[7]),
        "clock_mem_mhz":   _to_float(parts[8]),
        "clock_sm_mhz":    _to_float(parts[9]),
    }


def read_vmstat_oom_kills():
    try:
        with open("/proc/vmstat", "r") as f:
            for line in f:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except (IOError, ValueError):
        pass
    return -1


def read_top_gpu_proc():
    """Top GPU consumer via pynvml. Ritorna (pid, name, mib) o (-1, none, 0)."""
    procs = _safe_nvml_procs()
    if not procs:
        return -1, "none", 0
    top = max(procs, key=lambda p: p.usedGpuMemory)
    name = "unknown"
    try:
        with open(f"/proc/{top.pid}/comm", "r") as f:
            name = f.read().strip()
    except (IOError, FileNotFoundError):
        pass
    return top.pid, name, top.usedGpuMemory // (1024 * 1024)


def read_gpu_total_alloc_mib():
    """Somma della memoria GPU allocata da tutti i processi (in MiB)."""
    procs = _safe_nvml_procs()
    if not procs:
        return 0
    return sum(p.usedGpuMemory for p in procs) // (1024 * 1024)


def _safe_nvml_procs():
    try:
        pynvml.nvmlInit()
        handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        pynvml.nvmlShutdown()
        return procs or []
    except Exception:
        return []


def read_driver_errors():
    """Conta errori driver recenti in dmesg (NVRM, NVRM: GPU BUG, etc.)."""
    # dmesg con --since richiede root solitamente; proviamo journalctl come fallback
    for cmd in (
        ["journalctl", "-k", "--since=-30s", "-p", "err", "--no-pager", "-q"],
        ["dmesg", "--since=-30s", "--level=err,crit,alert,emerg"],
    ):
        try:
            out = subprocess.check_output(cmd, stderr=subprocess.DEVNULL, timeout=1.5)
            return out.decode("utf-8", errors="replace").count("\n")
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
            continue
    return -1


def _fmt(v):
    """Format valore per CSV: 'N/A' se None o stringa vuota, altrimenti il valore."""
    if v is None:
        return "N/A"
    if isinstance(v, str) and v.strip() == "":
        return "N/A"
    return v


def _to_float(s):
    if s in (None, "N/A", "[N/A]"):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def main():
    parser = argparse.ArgumentParser(description="VRAM Shield real-time stress monitor")
    parser.add_argument("--hz", type=float, default=2.0, help="Sample rate in Hz (default: 2.0)")
    parser.add_argument("--out", type=str, default=None,
                        help="CSV path. Default: outputs/monitor_YYYYMMDD_HHMMSS.csv")
    parser.add_argument("--duration", type=int, default=0,
                        help="Auto-stop after N seconds (0 = until SIGINT/SIGTERM, default: 0)")
    args = parser.parse_args()

    interval = 1.0 / max(args.hz, 0.1)

    if args.out:
        out_path = args.out
    else:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join("outputs", f"monitor_{ts}.csv")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    f_out = open(out_path, "w", newline="", buffering=1)  # line-buffered
    writer = csv.writer(f_out)
    writer.writerow([
        "timestamp", "epoch_ms",
        # GPU
        "gpu_temp_c", "gpu_power_w", "gpu_util_pct",
        "gpu_clock_graph_mhz", "gpu_clock_sm_mhz", "gpu_clock_mem_mhz",
        "gpu_mem_used_mib", "gpu_alloc_total_mib",
        # CPU
        "cpu_max_temp_c", "cpu_avg_temp_c", "cpu_avg_freq_mhz", "cpu_max_freq_mhz", "cpu_util_pct",
        # System memory (psutil)
        "sys_mem_total_mib", "sys_mem_used_mib", "sys_mem_available_mib", "sys_mem_pct",
        # Dashboard equivalent (GB10 unified memory, psutil + 8 GB overhead)
        "dashboard_equiv_mib", "dashboard_equiv_gb",
        # Alerts / events
        "oom_kill_total", "driver_err_30s",
        # Top GPU proc
        "top_gpu_pid", "top_gpu_name", "top_gpu_used_mib",
        # Flags
        "alert_gpu_thermal", "alert_cpu_thermal", "alert_mem_crit",
    ])
    f_out.flush()
    print(f"[monitor_ext] writing to {out_path}, hz={args.hz}", flush=True)

    stop = {"flag": False}

    def _sig(*_):
        stop["flag"] = True

    signal.signal(signal.SIGINT, _sig)
    signal.signal(signal.SIGTERM, _sig)

    # Prime psutil.cpu_percent to avoid first-call spike
    psutil.cpu_percent(interval=None)

    t_start = time.time()
    while not stop["flag"]:
        if args.duration > 0 and (time.time() - t_start) >= args.duration:
            print(f"[monitor_realtime] duration {args.duration}s reached, stopping.", flush=True)
            break
        t0 = time.time()
        now = datetime.now()
        epoch_ms = int(t0 * 1000)

        gpu = read_nvidia_smi_csv()
        cpu_max_c, cpu_zones = read_cpu_thermal_zones()
        cpu_avg, cpu_max = read_cpu_freq_mhz()
        cpu_util = read_cpu_util_pct()
        sys_mem = psutil.virtual_memory()
        oom = read_vmstat_oom_kills()
        drv = read_driver_errors()
        top_pid, top_name, top_mib = read_top_gpu_proc()
        gpu_total_mib = read_gpu_total_alloc_mib()

        cpu_avg_c = (sum(t for _, t in cpu_zones) / len(cpu_zones)) if cpu_zones else None
        sys_used_mib = sys_mem.used // (1024 * 1024)
        sys_total_mib = sys_mem.total // (1024 * 1024)
        dashboard_equiv_mib = sys_used_mib + GB10_DASHBOARD_OVERHEAD_MIB
        dashboard_equiv_gb = round(dashboard_equiv_mib / 1024.0, 1)

        row = [
            now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}",
            epoch_ms,
            _fmt(gpu["temp_c"] if gpu else None),
            _fmt(gpu["power_w"] if gpu else None),
            _fmt(gpu["util_gpu_pct"] if gpu else None),
            _fmt(gpu["clock_graph_mhz"] if gpu else None),
            _fmt(gpu["clock_sm_mhz"] if gpu else None),
            _fmt(gpu["clock_mem_mhz"] if gpu else None),
            _fmt(gpu["mem_used_mib"] if gpu else None),
            _fmt(gpu_total_mib),
            _fmt(cpu_max_c),
            _fmt(cpu_avg_c),
            _fmt(cpu_avg),
            _fmt(cpu_max),
            _fmt(cpu_util),
            sys_total_mib,
            sys_used_mib,
            sys_mem.available // (1024 * 1024),
            sys_mem.percent,
            dashboard_equiv_mib,
            dashboard_equiv_gb,
            oom,
            drv,
            top_pid,
            top_name,
            top_mib,
            1 if (gpu and gpu["temp_c"] and gpu["temp_c"] >= THERMAL_WARN_C) else 0,
            1 if (cpu_max_c and cpu_max_c >= CPU_THERMAL_WARN_C) else 0,
            1 if sys_mem.percent >= MEM_CRIT_PCT else 0,
        ]
        try:
            writer.writerow(row)
        except Exception as e:
            print(f"[monitor_ext] write error: {e}", file=sys.stderr, flush=True)

        dt = time.time() - t0
        if dt < interval:
            time.sleep(interval - dt)

    f_out.close()
    print(f"[monitor_ext] stopped, file: {out_path}", flush=True)


if __name__ == "__main__":
    main()
