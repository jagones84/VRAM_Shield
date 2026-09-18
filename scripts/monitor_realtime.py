#!/usr/bin/env python3
"""VRAM Shield real-time monitor with crash forensics telemetry."""

from __future__ import annotations

import argparse
import csv
import glob
import os
import signal
import subprocess
import sys
import time
from datetime import datetime
from typing import Dict, List, Optional, Sequence, Tuple

try:
    import psutil
except ImportError:
    print("FATAL: psutil not installed. pip install psutil", file=sys.stderr)
    sys.exit(1)

try:
    import pynvml
except ImportError:
    print("FATAL: pynvml not installed. pip install nvidia-ml-py", file=sys.stderr)
    sys.exit(1)


THERMAL_WARN_C = 85
CPU_THERMAL_WARN_C = 85
MEM_CRIT_PCT = 95
GB10_DASHBOARD_OVERHEAD_MIB = 8192
ACPITZ_EXPECTED_COUNT = 7
NVME_EXPECTED_COUNT = 3
MLX5_EXPECTED_COUNT = 4

_NVML_INITIALIZED = False
_NVML_HANDLE = None


def _run_command(args: Sequence[str], timeout: float = 2.0) -> Optional[str]:
    try:
        out = subprocess.check_output(
            list(args),
            stderr=subprocess.DEVNULL,
            timeout=timeout,
        )
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, FileNotFoundError, PermissionError):
        return None
    return out.decode("utf-8", errors="replace").strip()


def _to_float(value: Optional[str]) -> Optional[float]:
    if value in (None, "", "N/A", "[N/A]"):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt(value: object) -> object:
    if value is None:
        return "N/A"
    if isinstance(value, str) and value.strip() == "":
        return "N/A"
    return value


def _read_text(path: str) -> Optional[str]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as handle:
            return handle.read().strip()
    except (FileNotFoundError, OSError):
        return None


def _read_millideg_c(path: str) -> Optional[float]:
    raw = _read_text(path)
    if raw is None:
        return None
    try:
        return int(raw) / 1000.0
    except ValueError:
        return None


def _pad(values: List[Optional[float]], count: int) -> List[Optional[float]]:
    padded = list(values[:count])
    while len(padded) < count:
        padded.append(None)
    return padded


def _init_nvml():
    global _NVML_INITIALIZED, _NVML_HANDLE
    if _NVML_INITIALIZED:
        return _NVML_HANDLE
    try:
        pynvml.nvmlInit()
        _NVML_HANDLE = pynvml.nvmlDeviceGetHandleByIndex(0)
    except Exception:
        _NVML_HANDLE = None
    _NVML_INITIALIZED = True
    return _NVML_HANDLE


def _shutdown_nvml() -> None:
    global _NVML_INITIALIZED, _NVML_HANDLE
    if not _NVML_INITIALIZED:
        return
    try:
        pynvml.nvmlShutdown()
    except Exception:
        pass
    _NVML_INITIALIZED = False
    _NVML_HANDLE = None


def _safe_nvml_procs():
    handle = _init_nvml()
    if handle is None:
        return []
    try:
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
    except Exception:
        return []
    return procs or []


def read_nvidia_smi_csv() -> Optional[Dict[str, Optional[float]]]:
    out = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=index,temperature.gpu,power.draw,utilization.gpu,"
            "utilization.memory,memory.used,memory.free,clocks.current.graphics,"
            "clocks.current.memory,clocks.current.sm,clocks.max.graphics,clocks.max.sm",
            "--format=csv,noheader,nounits",
        ]
    )
    if not out:
        return None
    parts = [part.strip() for part in out.splitlines()[0].split(",")]
    if len(parts) < 12:
        return None
    return {
        "temp_c": _to_float(parts[1]),
        "power_w": _to_float(parts[2]),
        "util_gpu_pct": _to_float(parts[3]),
        "util_mem_pct": _to_float(parts[4]),
        "mem_used_mib": _to_float(parts[5]),
        "mem_free_mib": _to_float(parts[6]),
        "clock_graph_mhz": _to_float(parts[7]),
        "clock_mem_mhz": _to_float(parts[8]),
        "clock_sm_mhz": _to_float(parts[9]),
        "clock_max_graph_mhz": _to_float(parts[10]),
        "clock_max_sm_mhz": _to_float(parts[11]),
    }


def read_gpu_throttle_state() -> Dict[str, str]:
    out = _run_command(
        [
            "nvidia-smi",
            "--query-gpu=clocks_throttle_reasons.active,"
            "clocks_throttle_reasons.hw_thermal_slowdown,"
            "clocks_throttle_reasons.sw_thermal_slowdown,"
            "clocks_throttle_reasons.hw_power_brake_slowdown,"
            "clocks_throttle_reasons.hw_slowdown,"
            "clocks_throttle_reasons.gpu_idle",
            "--format=csv,noheader",
        ]
    )
    if not out:
        return {
            "active": "N/A",
            "hw_thermal": "N/A",
            "sw_thermal": "N/A",
            "hw_power_brake": "N/A",
            "hw_slowdown": "N/A",
            "gpu_idle": "N/A",
        }
    parts = [part.strip() for part in out.splitlines()[0].split(",")]
    while len(parts) < 6:
        parts.append("N/A")
    return {
        "active": parts[0],
        "hw_thermal": parts[1],
        "sw_thermal": parts[2],
        "hw_power_brake": parts[3],
        "hw_slowdown": parts[4],
        "gpu_idle": parts[5],
    }


def read_acpitz_zone_temps() -> List[Optional[float]]:
    temps: List[Optional[float]] = []
    for zone_dir in sorted(glob.glob("/sys/class/thermal/thermal_zone*")):
        zone_type = _read_text(os.path.join(zone_dir, "type"))
        if zone_type != "acpitz":
            continue
        temps.append(_read_millideg_c(os.path.join(zone_dir, "temp")))
    return _pad(temps, ACPITZ_EXPECTED_COUNT)


def read_cpu_thermal_summary() -> Tuple[Optional[float], Optional[float], List[Optional[float]]]:
    zones = read_acpitz_zone_temps()
    present = [temp for temp in zones if temp is not None]
    if not present:
        return None, None, zones
    return max(present), sum(present) / len(present), zones


def read_cpu_freq_mhz() -> Tuple[Optional[float], Optional[float]]:
    freqs: List[float] = []
    for path in sorted(glob.glob("/sys/devices/system/cpu/cpu[0-9]*/cpufreq/scaling_cur_freq")):
        raw = _read_text(path)
        if raw is None:
            continue
        try:
            freqs.append(int(raw) / 1000.0)
        except ValueError:
            continue
    if not freqs:
        return None, None
    return sum(freqs) / len(freqs), max(freqs)


def read_cpu_util_pct() -> float:
    return psutil.cpu_percent(interval=None)


def read_hwmon_temps() -> Dict[str, List[Optional[float]]]:
    nvme_temps: List[Optional[float]] = []
    mlx5_temps: List[Optional[float]] = []
    wifi_temp: Optional[float] = None

    for hwmon_dir in sorted(glob.glob("/sys/class/hwmon/hwmon*")):
        name = _read_text(os.path.join(hwmon_dir, "name"))
        if not name:
            continue
        temps = []
        for temp_path in sorted(glob.glob(os.path.join(hwmon_dir, "temp*_input"))):
            value = _read_millideg_c(temp_path)
            if value is not None:
                temps.append(value)
        if name == "nvme":
            nvme_temps.extend(temps)
        elif name == "mlx5":
            if temps:
                mlx5_temps.append(temps[0])
        elif name == "mt7925_phy0":
            if temps and wifi_temp is None:
                wifi_temp = temps[0]

    return {
        "nvme": _pad(nvme_temps, NVME_EXPECTED_COUNT),
        "mlx5": _pad(mlx5_temps, MLX5_EXPECTED_COUNT),
        "wifi": [wifi_temp],
    }


def read_vmstat_oom_kills() -> int:
    try:
        with open("/proc/vmstat", "r", encoding="utf-8", errors="replace") as handle:
            for line in handle:
                if line.startswith("oom_kill "):
                    return int(line.split()[1])
    except (OSError, ValueError):
        pass
    return -1


def read_top_gpu_proc() -> Tuple[int, str, int]:
    procs = _safe_nvml_procs()
    if not procs:
        return -1, "none", 0
    top = max(procs, key=lambda proc: getattr(proc, "usedGpuMemory", 0))
    name = _read_text(f"/proc/{top.pid}/comm") or "unknown"
    used_mib = int(getattr(top, "usedGpuMemory", 0) // (1024 * 1024))
    return int(top.pid), name, used_mib


def read_gpu_total_alloc_mib() -> int:
    procs = _safe_nvml_procs()
    if not procs:
        return 0
    total = sum(int(getattr(proc, "usedGpuMemory", 0)) for proc in procs)
    return total // (1024 * 1024)


def read_driver_errors() -> int:
    commands = (
        ["journalctl", "-k", "--since=-30s", "-p", "err", "--no-pager", "-q"],
        ["dmesg", "--since=-30s", "--level=err,crit,alert,emerg"],
    )
    for command in commands:
        out = _run_command(command, timeout=1.5)
        if out is not None:
            return out.count("\n") + (1 if out else 0)
    return -1


def build_header() -> List[str]:
    header = [
        "timestamp", "epoch_ms",
        "gpu_temp_c", "gpu_power_w", "gpu_util_pct",
        "gpu_clock_graph_mhz", "gpu_clock_sm_mhz", "gpu_clock_mem_mhz",
        "gpu_mem_used_mib", "gpu_alloc_total_mib",
        "cpu_max_temp_c", "cpu_avg_temp_c", "cpu_avg_freq_mhz", "cpu_max_freq_mhz", "cpu_util_pct",
        "sys_mem_total_mib", "sys_mem_used_mib", "sys_mem_available_mib", "sys_mem_pct",
        "dashboard_equiv_mib", "dashboard_equiv_gb",
        "oom_kill_total", "driver_err_30s",
        "top_gpu_pid", "top_gpu_name", "top_gpu_used_mib",
        "alert_gpu_thermal", "alert_cpu_thermal", "alert_mem_crit",
        "gpu_util_mem_pct", "gpu_mem_free_mib", "gpu_clock_max_graph_mhz", "gpu_clock_max_sm_mhz",
    ]
    header.extend([f"acpitz_zone{i}_c" for i in range(ACPITZ_EXPECTED_COUNT)])
    header.extend([f"nvme_temp{i}_c" for i in range(1, NVME_EXPECTED_COUNT + 1)])
    header.extend([f"mlx5_{i}_temp_c" for i in range(MLX5_EXPECTED_COUNT)])
    header.extend(
        [
            "wifi_temp_c",
            "gpu_throttle_active",
            "gpu_throttle_hw_thermal",
            "gpu_throttle_sw_thermal",
            "gpu_throttle_hw_power_brake",
            "gpu_throttle_hw_slowdown",
            "gpu_throttle_gpu_idle",
        ]
    )
    return header


def main() -> int:
    parser = argparse.ArgumentParser(description="VRAM Shield real-time stress monitor")
    parser.add_argument("--hz", type=float, default=2.0, help="Sample rate in Hz (default: 2.0)")
    parser.add_argument("--out", type=str, default=None, help="CSV path")
    parser.add_argument("--duration", type=int, default=0, help="Auto-stop after N seconds")
    args = parser.parse_args()

    interval = 1.0 / max(args.hz, 0.1)
    if args.out:
        out_path = args.out
    else:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = os.path.join("outputs", f"monitor_{stamp}.csv")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)

    stop = {"flag": False}

    def _handle_signal(*_args) -> None:
        stop["flag"] = True

    signal.signal(signal.SIGINT, _handle_signal)
    signal.signal(signal.SIGTERM, _handle_signal)

    psutil.cpu_percent(interval=None)
    start_time = time.time()

    with open(out_path, "w", newline="", buffering=1, encoding="utf-8") as out_file:
        writer = csv.writer(out_file)
        writer.writerow(build_header())
        out_file.flush()
        os.fsync(out_file.fileno())
        print(f"[monitor_realtime] writing to {out_path}, hz={args.hz}", flush=True)

        while not stop["flag"]:
            if args.duration > 0 and (time.time() - start_time) >= args.duration:
                print(f"[monitor_realtime] duration {args.duration}s reached, stopping.", flush=True)
                break

            tick_start = time.time()
            now = datetime.now()
            epoch_ms = int(tick_start * 1000)

            gpu = read_nvidia_smi_csv()
            throttle = read_gpu_throttle_state()
            cpu_max_c, cpu_avg_c, acpitz_zones = read_cpu_thermal_summary()
            cpu_avg_mhz, cpu_max_mhz = read_cpu_freq_mhz()
            cpu_util_pct = read_cpu_util_pct()
            hwmon = read_hwmon_temps()
            sys_mem = psutil.virtual_memory()
            sys_total_mib = sys_mem.total // (1024 * 1024)
            sys_used_mib = sys_mem.used // (1024 * 1024)
            sys_available_mib = sys_mem.available // (1024 * 1024)
            dashboard_equiv_mib = sys_used_mib + GB10_DASHBOARD_OVERHEAD_MIB
            dashboard_equiv_gb = round(dashboard_equiv_mib / 1024.0, 1)
            oom_kill_total = read_vmstat_oom_kills()
            driver_err_30s = read_driver_errors()
            top_gpu_pid, top_gpu_name, top_gpu_used_mib = read_top_gpu_proc()
            gpu_alloc_total_mib = read_gpu_total_alloc_mib()

            row: List[object] = [
                now.strftime("%Y-%m-%d %H:%M:%S.") + f"{now.microsecond // 1000:03d}",
                epoch_ms,
                _fmt(gpu["temp_c"] if gpu else None),
                _fmt(gpu["power_w"] if gpu else None),
                _fmt(gpu["util_gpu_pct"] if gpu else None),
                _fmt(gpu["clock_graph_mhz"] if gpu else None),
                _fmt(gpu["clock_sm_mhz"] if gpu else None),
                _fmt(gpu["clock_mem_mhz"] if gpu else None),
                _fmt(gpu["mem_used_mib"] if gpu else None),
                _fmt(gpu_alloc_total_mib),
                _fmt(cpu_max_c),
                _fmt(cpu_avg_c),
                _fmt(cpu_avg_mhz),
                _fmt(cpu_max_mhz),
                _fmt(cpu_util_pct),
                sys_total_mib,
                sys_used_mib,
                sys_available_mib,
                sys_mem.percent,
                dashboard_equiv_mib,
                dashboard_equiv_gb,
                oom_kill_total,
                driver_err_30s,
                top_gpu_pid,
                top_gpu_name,
                top_gpu_used_mib,
                1 if (gpu and gpu["temp_c"] is not None and gpu["temp_c"] >= THERMAL_WARN_C) else 0,
                1 if (cpu_max_c is not None and cpu_max_c >= CPU_THERMAL_WARN_C) else 0,
                1 if sys_mem.percent >= MEM_CRIT_PCT else 0,
                _fmt(gpu["util_mem_pct"] if gpu else None),
                _fmt(gpu["mem_free_mib"] if gpu else None),
                _fmt(gpu["clock_max_graph_mhz"] if gpu else None),
                _fmt(gpu["clock_max_sm_mhz"] if gpu else None),
            ]

            row.extend(_fmt(value) for value in acpitz_zones)
            row.extend(_fmt(value) for value in hwmon["nvme"])
            row.extend(_fmt(value) for value in hwmon["mlx5"])
            row.extend(
                [
                    _fmt(hwmon["wifi"][0]),
                    throttle["active"],
                    throttle["hw_thermal"],
                    throttle["sw_thermal"],
                    throttle["hw_power_brake"],
                    throttle["hw_slowdown"],
                    throttle["gpu_idle"],
                ]
            )

            try:
                writer.writerow(row)
                out_file.flush()
                os.fsync(out_file.fileno())
            except Exception as exc:
                print(f"[monitor_realtime] write error: {exc}", file=sys.stderr, flush=True)

            elapsed = time.time() - tick_start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    _shutdown_nvml()
    print(f"[monitor_realtime] stopped, file: {out_path}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
