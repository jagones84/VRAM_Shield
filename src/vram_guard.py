import time
import sys
import os
import signal
import argparse
import platform
from datetime import datetime

# Try to import pynvml and psutil, provide instructions if missing
try:
    import pynvml
except ImportError:
    print("Error: 'pynvml' library is missing.")
    print("Please install it using: pip install nvidia-ml-py")
    sys.exit(1)

try:
    import psutil
except ImportError:
    print("Error: 'psutil' library is missing.")
    print("Please install it using: pip install psutil")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print("Error: 'PyYAML' library is missing.")
    print("Please install it using: pip install PyYAML")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("Warning: 'python-dotenv' library is missing. Environment variables from .env will not be loaded.")
    print("Please install it using: pip install python-dotenv")
    # Do not exit, as it's a warning, not a critical error for core functionality


def get_process_name(pid):
    """Retrieve the name of a process given its PID, or 'Unknown' if not found."""
    try:
        proc = psutil.Process(pid)
        return proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "Unknown"

def get_process_vms_mb(pid):
    """Fallback: get the Virtual Memory Size (VMS) in MB from the OS for a given PID.
    We use VMS instead of RSS (Resident Set Size) because Unified Memory allocations 
    (like cudaMemAlloc) reserve virtual memory instantly, but RSS only grows slowly 
    due to demand paging when pages are actually touched. VMS catches OOM hazards immediately."""
    try:
        proc = psutil.Process(pid)
        return proc.memory_info().vms / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0

def kill_process(pid, process_name):
    """Forcefully and instantly kill a process using SIGKILL."""
    print(f"!!! KILLING process {process_name} (PID: {pid}) !!!")
    try:
        if platform.system() == "Windows":
            os.kill(pid, signal.SIGTERM) # Windows doesn't have SIGKILL
        else:
            os.kill(pid, signal.SIGKILL)
        print(f"Process {pid} terminated instantly.")
    except Exception as e:
        print(f"Failed to kill process {pid}: {e}")

def setup_autostart():
    """Configure cross-platform autostart based on OS."""
    os_name = platform.system()
    app_name = "VRAMGuard"
    script_path = os.path.abspath(__file__)
    
    if os_name == "Windows":
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
            # Run hidden in background on Windows
            cmd = f'pythonw.exe "{script_path}"'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            print("Windows Autostart configured in Registry.")
        except Exception as e:
            print(f"Failed to set Windows autostart: {e}")
            
    elif os_name == "Linux":
        # Systemd is preferred for servers, but we can set up .desktop for user UI autostart
        autostart_dir = os.path.expanduser("~/.config/autostart")
        if os.path.exists(autostart_dir):
            desktop_file = os.path.join(autostart_dir, "vram_guard.desktop")
            wrapper_script = os.path.join(os.path.dirname(os.path.dirname(script_path)), "scripts", "run_guard.sh")
            if os.path.exists(wrapper_script):
                content = f"""[Desktop Entry]
Type=Application
Exec={wrapper_script} --background
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
Name[en_US]=VRAM Guard
Name=VRAM Guard
Comment=NVIDIA VRAM Protection
"""
                try:
                    with open(desktop_file, "w") as f:
                        f.write(content)
                    print("Linux .desktop Autostart configured successfully.")
                except Exception as e:
                    print(f"Failed to write .desktop file: {e}")
    else:
        print(f"Autostart not supported on {os_name}")

def monitor_vram():
    """Monitor VRAM usage based on config.yaml."""
    # Load config file
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.yaml")
    if not os.path.exists(config_path):
        print(f"Error: Config file not found at {config_path}")
        sys.exit(1)
        
    with open(config_path, 'r') as f:
        config = yaml.safe_load(f)
        
    threshold = config.get('threshold', 126000)
    interval = config.get('interval', 1.0)
    gpu_index = config.get('gpu_index', 0)
    dry_run = config.get('dry_run', False)
    whitelist = config.get('whitelist_pids', [])
    mode = config.get('mode', 'PROCESS')
    autostart = config.get('autostart', False)
    
    if autostart:
        setup_autostart()
    
    # Load environment variables (optional, for future extensions)
    dotenv_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    if os.path.exists(dotenv_path):
        load_dotenv(dotenv_path)

    pynvml.nvmlInit()
    try:
        handle = pynvml.nvmlDeviceGetHandleByIndex(gpu_index)
        device_name = pynvml.nvmlDeviceGetName(handle)
        if isinstance(device_name, bytes):
            device_name = device_name.decode('utf-8')
            
        print(f"Monitoring GPU {gpu_index}: {device_name}")
        
        try:
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_vram = mem_info.total / (1024 * 1024)
            print(f"Total VRAM: {total_vram:.1f} MB")
        except pynvml.NVMLError as e:
            if "Not Supported" in str(e):
                print("Total VRAM: Unknown (Unified Memory / Not Supported)")
                print("Mode: Per-process monitoring only (sum of process usage)")
                total_vram = float('inf')
            else:
                raise e

        print(f"Threshold: {threshold} MB")
        print(f"Mode: {mode} protection")
        print(f"Interval: {interval}s")
        print("-" * 50)
        
        while True:
            try:
                processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                
                # Check for memory spikes
                total_used = 0
                max_vram_proc = None
                max_vram_usage = 0
                max_vram_name = ""
                
                for proc in processes:
                    if proc.pid in whitelist:
                        continue
                        
                    proc_name = get_process_name(proc.pid)
                    
                    vms_val = get_process_vms_mb(proc.pid)
                    nvml_val = (proc.usedGpuMemory or 0) / (1024 * 1024)
                    
                    # On GB10 Unified Memory, NVML might report 0 or small values.
                    # VMS catches the virtual allocation instantly. We take the max.
                    vram_used = max(vms_val, nvml_val)
                        
                    total_used += vram_used
                    
                    # Keep track of largest process for SYSTEM mode
                    if vram_used > max_vram_usage:
                        max_vram_usage = vram_used
                        max_vram_proc = proc.pid
                        max_vram_name = proc_name
                        
                    # PROCESS mode logic
                    if mode.upper() == "PROCESS":
                        if vram_used > threshold:
                            timestamp = time.strftime("%H:%M:%S")
                            print(f"[{timestamp}] ALERT: Process '{proc_name}' (PID: {proc.pid}) using {vram_used:.1f} MB (Threshold: {threshold} MB)")
                            if not dry_run:
                                kill_process(proc.pid, proc_name)
                                time.sleep(1) # Let system recover before checking again
                
                # SYSTEM mode logic
                if mode.upper() == "SYSTEM":
                    if total_used > threshold and max_vram_proc is not None:
                        timestamp = time.strftime("%H:%M:%S")
                        print(f"[{timestamp}] SYSTEM ALERT: Total VRAM {total_used:.1f} MB exceeds {threshold} MB limit!")
                        print(f"[{timestamp}] Killing top consumer '{max_vram_name}' (PID: {max_vram_proc}) using {max_vram_usage:.1f} MB")
                        if not dry_run:
                            kill_process(max_vram_proc, max_vram_name)
                            time.sleep(1)
                            
            except pynvml.NVMLError as err:
                print(f"NVML Error: {err}")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        print("\nMonitoring stopped.")
    finally:
        pynvml.nvmlShutdown()

if __name__ == "__main__":
    # Create PID file
    pid_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".vram_guard.pid")
    with open(pid_file, "w") as f:
        f.write(str(os.getpid()))

    try:
        monitor_vram()
    finally:
        if os.path.exists(pid_file):
            os.remove(pid_file)
