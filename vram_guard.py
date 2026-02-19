import time
import sys
import os
import signal
import argparse
from datetime import datetime

# Try to import pynvml, provide instructions if missing
try:
    import pynvml
except ImportError:
    print("Error: 'pynvml' library is missing.")
    print("Please install it using: pip install nvidia-ml-py")
    sys.exit(1)

def get_process_name(pid):
    """Get process name from PID."""
    try:
        with open(f'/proc/{pid}/cmdline', 'r') as f:
            cmdline = f.read().split('\x00')
            return cmdline[0] if cmdline else "Unknown"
    except (FileNotFoundError, PermissionError):
        return "Unknown"

def kill_process(pid, name, dry_run=False):
    """Kill a process."""
    if dry_run:
        print(f"[DRY-RUN] Would kill process {name} (PID: {pid})")
        return

    try:
        print(f"!!! KILLING process {name} (PID: {pid}) !!!")
        os.kill(pid, signal.SIGTERM)
        # Give it a second to die, then force kill if needed
        time.sleep(1)
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass # Already dead
        print(f"Process {pid} terminated.")
    except PermissionError:
        print(f"Error: No permission to kill process {pid}. Run as sudo?")
    except ProcessLookupError:
        print(f"Process {pid} already exited.")

def monitor_vram(threshold_mb, interval=1.0, gpu_index=0, dry_run=False, whitelist=None, mode="process"):
    """Monitor VRAM and enforce threshold."""
    if whitelist is None:
        whitelist = []

    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        gpu_name = pynvml.nvmlDeviceGetName(handle)
        
        # Handle bytes vs string return type for older/newer pynvml versions
        if isinstance(gpu_name, bytes):
            gpu_name = gpu_name.decode('utf-8')
            
        print(f"Monitoring GPU {gpu_index}: {gpu_name}")
        
        # Check if global memory info is supported
        try:
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            print(f"Total VRAM: {mem_info.total / 1024 / 1024:.0f} MB")
        except pynvml.NVMLError:
            print("Total VRAM: Unknown (Unified Memory / Not Supported)")
            print("Mode: Per-process monitoring only (sum of process usage)")

        print(f"Threshold: {threshold_mb} MB")
        print(f"Mode: {mode.upper()} protection")
        print(f"Interval: {interval}s")
        if dry_run:
            print("Mode: DRY RUN (No processes will be killed)")
        
        print("-" * 50)

        while True:
            # Get running processes on GPU first
            procs = []
            try:
                procs += pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
            except pynvml.NVMLError:
                pass

            try:
                procs += pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
            except pynvml.NVMLError:
                pass

            # Deduplicate processes based on PID
            unique_procs = {p.pid: p for p in procs}.values()

            # Calculate total used memory from processes if global info fails
            # We use this as the primary metric for "Total" mode on GB10
            current_usage_mb = sum(p.usedGpuMemory for p in unique_procs if p.usedGpuMemory) / 1024 / 1024

            timestamp = datetime.now().strftime("%H:%M:%S")

            if mode == "total":
                # TOTAL MODE: Check if sum of all processes exceeds threshold
                if current_usage_mb > threshold_mb:
                    print(f"[{timestamp}] ALERT: Total System VRAM ({current_usage_mb:.1f} MB) > Threshold ({threshold_mb} MB)")
                    
                    # Find the largest non-whitelisted process to kill
                    candidates = []
                    for p in unique_procs:
                        if p.usedGpuMemory is None: continue
                        name = get_process_name(p.pid)
                        if not any(w in name for w in whitelist):
                            candidates.append((p.usedGpuMemory, p.pid, name))
                    
                    if candidates:
                        # Sort by memory usage (descending)
                        candidates.sort(key=lambda x: x[0], reverse=True)
                        victim_mem, victim_pid, victim_name = candidates[0]
                        victim_mem_mb = victim_mem / 1024 / 1024
                        
                        print(f"[{timestamp}] ACTION: Killing largest process '{victim_name}' (PID: {victim_pid}) using {victim_mem_mb:.1f} MB")
                        kill_process(victim_pid, victim_name, dry_run)
                    else:
                        print(f"[{timestamp}] WARNING: Threshold exceeded but all processes are whitelisted!")

            else:
                # PROCESS MODE: Check each process individually
                for p in unique_procs:
                    if p.usedGpuMemory is None:
                        continue
                    
                    proc_mem_mb = p.usedGpuMemory / 1024 / 1024
                    proc_name = get_process_name(p.pid)
                    
                    # Check if process exceeds threshold
                    if proc_mem_mb > threshold_mb:
                        is_whitelisted = any(w in proc_name for w in whitelist)
                        
                        print(f"[{timestamp}] ALERT: Process '{proc_name}' (PID: {p.pid}) using {proc_mem_mb:.1f} MB (Threshold: {threshold_mb} MB)")
                        
                        if not is_whitelisted:
                            kill_process(p.pid, proc_name, dry_run)
                        else:
                            print(f"Process '{proc_name}' is whitelisted. Skipping.")

            time.sleep(interval)

    except KeyboardInterrupt:
        print("\nStopping VRAM Guard.")
    except pynvml.NVMLError as e:
        print(f"NVML Error: {e}")
    finally:
        pynvml.nvmlShutdown()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Monitor and protect NVIDIA GPU VRAM.")
    parser.add_argument("--threshold", type=int, required=True, help="Limit in MB. In 'process' mode: per-process limit. In 'total' mode: system-wide limit.")
    parser.add_argument("--mode", choices=["process", "total"], default="process", help="Protection mode. 'process' kills any single process > threshold. 'total' kills largest process if system sum > threshold.")
    parser.add_argument("--interval", type=float, default=1.0, help="Monitoring interval in seconds")
    parser.add_argument("--gpu", type=int, default=0, help="GPU index to monitor (default 0)")
    parser.add_argument("--dry-run", action="store_true", help="Monitor only, do not kill processes")
    parser.add_argument("--whitelist", nargs="*", default=["Xorg", "gnome-shell"], help="List of process names to ignore")
    
    args = parser.parse_args()
    
    monitor_vram(args.threshold, args.interval, args.gpu, args.dry_run, args.whitelist, args.mode)
