import os
import sys
import time
import subprocess
import psutil
from datetime import datetime

try:
    import pynvml
except ImportError:
    pynvml = None

# Configuration
GPU_BURN_PATH = "/home/jagones/gpu-burn/gpu-burn/gpu_burn"
GPU_BURN_DIR = "/home/jagones/gpu-burn/gpu-burn"
LOG_FILE = "/home/jagones/Programs/VRAM_shield/calibration_data.log"

# Target test points in GB
TARGETS = [10, 30, 50]

def log_to_file(message):
    try:
        with open(LOG_FILE, "a") as f:
            f.write(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")
    except Exception as e:
        print(f"Error writing to log: {e}")

def run_test_point(target_gb):
    target_mb = int(target_gb * 1024)
    print(f"\n{'='*60}")
    print(f"RUNNING TEST POINT: {target_gb} GB ({target_mb} MB)")
    print(f"{'='*60}")
    
    cmd = [GPU_BURN_PATH, "-m", f"{target_mb}", "45"] # Run for 45 seconds to give time for observation
    
    # Start gpu-burn
    process = None
    try:
        process = subprocess.Popen(
            cmd,
            cwd=GPU_BURN_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
    except Exception as e:
        print(f"Error starting gpu-burn: {e}")
        return None

    print(f"gpu-burn started (PID {process.pid}).")
    print("Wait for allocation to stabilize (approx 5-10 seconds)...")
    
    # Wait for stabilization
    time.sleep(8)
    
    # Measure internal metrics
    max_rss = 0
    max_nvml = 0
    
    # Initialize NVML if possible
    handle = None
    if pynvml:
        try:
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
        except:
            pass

    # Monitor for a short window to get stable reading
    for _ in range(5):
        if process.poll() is not None:
            print("Process died early!")
            break
            
        try:
            p = psutil.Process(process.pid)
            rss = p.memory_info().rss / (1024 * 1024)
            if rss > max_rss: max_rss = rss
        except: pass
        
        if handle:
            try:
                procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                for p in procs:
                    if p.pid == process.pid:
                        nvml_val = (p.usedGpuMemory or 0) / (1024 * 1024)
                        if nvml_val > max_nvml: max_nvml = nvml_val
            except: pass
        
        time.sleep(1)

    print(f"\n--- MEASURED VALUES ---")
    print(f"Target:      {target_gb} GB")
    print(f"Shield RSS:  {max_rss:.2f} MB")
    print(f"Shield NVML: {max_nvml:.2f} MB")
    
    # User Input
    print(f"\n>>> ACTION REQUIRED <<<")
    print(f"Please look at your system monitor NOW.")
    while True:
        try:
            user_val = input(f"Enter the 'Real' memory usage value you see (in GB) for this {target_gb}GB test: ")
            user_gb = float(user_val)
            break
        except ValueError:
            print("Invalid input. Please enter a number (e.g., 19.5).")
    
    # Log data
    log_entry = f"TARGET_GB={target_gb}, TARGET_MB={target_mb}, RSS_MB={max_rss:.2f}, NVML_MB={max_nvml:.2f}, USER_OBSERVED_GB={user_gb}"
    log_to_file(log_entry)
    
    print(f"Data recorded: {log_entry}")
    
    # Cleanup
    if process and process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=2)
        except:
            process.kill()
            
    if pynvml:
        try: pynvml.nvmlShutdown()
        except: pass
        
    return {
        "target_gb": target_gb,
        "rss_mb": max_rss,
        "nvml_mb": max_nvml,
        "user_gb": user_gb
    }

def main():
    print("Starting Interactive Calibration Sequence")
    print("We will run 3 tests. For each test, please observe your system monitor and enter the value you see.")
    
    # Clear previous log
    with open(LOG_FILE, "w") as f:
        f.write(f"Calibration Session Started: {datetime.now()}\n")
        
    results = []
    
    for target in TARGETS:
        res = run_test_point(target)
        if res:
            results.append(res)
        time.sleep(3) # Cooldown
        
    print("\n" + "="*60)
    print("CALIBRATION COMPLETE")
    print("="*60)
    print(f"{'Target (GB)':<12} | {'User (GB)':<12} | {'RSS (MB)':<12} | {'NVML (MB)':<12} | {'Factor (User/Target)':<20}")
    print("-" * 80)
    
    for r in results:
        factor = r['user_gb'] / r['target_gb'] if r['target_gb'] > 0 else 0
        print(f"{r['target_gb']:<12} | {r['user_gb']:<12} | {r['rss_mb']:<12.1f} | {r['nvml_mb']:<12.1f} | {factor:<20.2f}")
        
    print(f"\nData saved to {LOG_FILE}")

if __name__ == "__main__":
    main()
