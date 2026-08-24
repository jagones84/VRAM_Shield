import os
import sys
import time
import subprocess
import psutil
from datetime import datetime

# Configuration
# Try to find gpu_burn in common locations
possible_paths = [
    "./gpu-burn/gpu_burn",
    "../gpu-burn/gpu_burn",
    "/home/jagones/gpu-burn/gpu-burn/gpu_burn", # Keep for backward compatibility
]

GPU_BURN_PATH = None
for path in possible_paths:
    if os.path.isfile(path):
        GPU_BURN_PATH = os.path.abspath(path)
        break

if not GPU_BURN_PATH:
    print("Error: gpu_burn executable not found!")
    print("Please install gpu-burn and place it in ./gpu-burn/ or ../gpu-burn/")
    sys.exit(1)

GPU_BURN_DIR = os.path.dirname(GPU_BURN_PATH)
SHIELD_THRESHOLD_MB = 35000  # Default 35 GB (Adjust as needed)

# Ramp Configuration
START_GB = 23.0
END_GB = 28.0
STEP_GB = 0.5
TEST_DURATION_SEC = 20  # How long to run each test to check for stability

def run_gpu_burn(target_gb):
    target_mb = int(target_gb * 1024)
    # Run slightly longer than test duration to ensure we catch it
    cmd = [GPU_BURN_PATH, "-m", f"{target_mb}", str(TEST_DURATION_SEC + 10)]
    
    try:
        process = subprocess.Popen(
            cmd,
            cwd=GPU_BURN_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return process
    except Exception as e:
        print(f"Error starting gpu-burn: {e}")
        return None

def monitor_process(process, target_gb):
    print(f"\n--- Testing Target: {target_gb:.1f} GB (PID {process.pid}) ---")
    
    start_time = time.time()
    killed = False
    
    # Wait loop
    while time.time() - start_time < TEST_DURATION_SEC:
        if process.poll() is not None:
            killed = True
            break
        
        # Check if process exists in psutil
        try:
            p = psutil.Process(process.pid)
        except psutil.NoSuchProcess:
            killed = True
            break
            
        time.sleep(1)
        sys.stdout.write(".")
        sys.stdout.flush()
        
    print()
    
    if killed:
        print(f"❌ KILLED by Shield! (Target: {target_gb:.1f} GB)")
        return False  # Failed/Killed
    else:
        print(f"✅ SAFE (Target: {target_gb:.1f} GB)")
        # Cleanup for next run
        process.terminate()
        try: process.wait(timeout=2)
        except: process.kill()
        return True   # Survived

def main():
    print("==========================================")
    print("      VRAM SHIELD RAMP-UP TEST")
    print("==========================================")
    print(f"Shield Threshold: {SHIELD_THRESHOLD_MB} MB (35 GB)")
    print(f"Range: {START_GB} GB -> {END_GB} GB (Step: {STEP_GB} GB)")
    print(f"Duration per step: {TEST_DURATION_SEC} seconds")
    print("------------------------------------------")
    
    current_gb = START_GB
    
    while current_gb <= END_GB:
        process = run_gpu_burn(current_gb)
        if not process:
            print("Failed to start process. Aborting.")
            break
            
        survived = monitor_process(process, current_gb)
        
        if not survived:
            print("\n" + "="*50)
            print(f"🚨 TRIGGER POINT FOUND: {current_gb:.1f} GB")
            print("="*50)
            break
        
        current_gb += STEP_GB
        print("Cooling down 5s...")
        time.sleep(5)
        
    if current_gb > END_GB:
        print("\nTest completed without triggering (Max target reached).")

if __name__ == "__main__":
    main()
