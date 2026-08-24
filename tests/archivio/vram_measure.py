"""VRAM measurement comparison: 7 different ways to read memory on GB10.

Usage:
    vram_measure.py baseline   # no load
    vram_measure.py under_load # 90 GB gpu-burn running in background (started separately)
"""
import sys
import subprocess
import json
import time

def humanize_mb(mb: float) -> str:
    if mb >= 1024:
        return f"{mb/1024:.2f} GiB ({mb:.0f} MB)"
    return f"{mb:.0f} MB"

def measure():
    results = {}

    # 1. nvidia-smi --query-gpu=memory.total
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    results["nvidia_smi_query_memory_total_MB"] = r.stdout.strip()

    # 2. nvidia-smi --query-gpu=memory.free
    r = subprocess.run(
        ["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    results["nvidia_smi_query_memory_free_MB"] = r.stdout.strip()

    # 3. nvidia-smi --query-compute-apps (per-process)
    r = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=pid,process_name,used_memory",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True
    )
    apps = []
    total = 0
    for line in r.stdout.strip().split("\n"):
        if not line.strip():
            continue
        parts = [p.strip() for p in line.split(",")]
        if len(parts) >= 3:
            try:
                used = int(parts[2])
            except ValueError:
                used = 0
            apps.append({"pid": parts[0], "name": parts[1], "used_mb": used})
            total += used
    results["nvidia_smi_compute_apps"] = apps
    results["nvidia_smi_compute_apps_total_MB"] = total

    # 4. pynvml.nvmlDeviceGetMemoryInfo (the only NVML total that works on GB10)
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(0)
        mi = pynvml.nvmlDeviceGetMemoryInfo(h)
        results["pynvml_memory_total_MB"] = round(mi.total / 1024 / 1024, 1)
        results["pynvml_memory_used_MB"] = round(mi.used / 1024 / 1024, 1)
        results["pynvml_memory_free_MB"] = round(mi.free / 1024 / 1024, 1)
        pynvml.nvmlShutdown()
    except Exception as e:
        results["pynvml_error"] = str(e)

    # 5. free -h (system RAM)
    r = subprocess.run(["free", "-h"], capture_output=True, text=True)
    results["free_h"] = r.stdout.strip()

    # 6. /proc/meminfo (kernel-reported)
    with open("/proc/meminfo") as f:
        for line in f:
            if line.startswith(("MemTotal:", "MemFree:", "MemAvailable:",
                                "Buffers:", "Cached:", "SReclaimable:",
                                "Shmem:", "Slab:")):
                results[f"proc_{line.split(':')[0]}"] = line.strip().split(":", 1)[1].strip()

    # 7. psutil.virtual_memory
    import psutil
    vm = psutil.virtual_memory()
    results["psutil_total_MB"] = round(vm.total / 1024 / 1024, 1)
    results["psutil_used_MB"] = round(vm.used / 1024 / 1024, 1)
    results["psutil_available_MB"] = round(vm.available / 1024 / 1024, 1)
    results["psutil_percent"] = vm.percent

    return results

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "baseline"
    print(f"=== VRAM measurement: {mode} ===")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")
    r = measure()
    print(json.dumps(r, indent=2, default=str))
