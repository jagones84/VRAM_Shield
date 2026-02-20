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
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: 'pynvml' library is missing.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Please install it using: pip install nvidia-ml-py")
    sys.exit(1)

try:
    import psutil
except ImportError:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: 'psutil' library is missing.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Please install it using: pip install psutil")
    sys.exit(1)

try:
    import yaml
except ImportError:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Error: 'PyYAML' library is missing.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Please install it using: pip install PyYAML")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Warning: 'python-dotenv' library is missing. Environment variables from .env will not be loaded.")
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] Please install it using: pip install python-dotenv")
    # Do not exit, as it's a warning, not a critical error for core functionality

def log(message):
    """Log a message with a timestamp."""
    print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}")

def get_process_name(pid):
    """Retrieve the name of a process given its PID, or 'Unknown' if not found."""
    try:
        proc = psutil.Process(pid)
        return proc.name()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "Unknown"

def get_process_rss_mb(pid):
    """Fallback: get the Resident Set Size (RSS) in MB from the OS for a given PID.
    We use RSS to track actual physical memory usage. VMS can be misleadingly high due
    to large virtual address space reservations (e.g. by Python or CUDA) that are not
    backed by physical RAM."""
    try:
        proc = psutil.Process(pid)
        return proc.memory_info().rss / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0

def kill_process(pid, process_name):
    """Forcefully and instantly kill a process using SIGKILL."""
    log(f"!!! KILLING process {process_name} (PID: {pid}) !!!")
    try:
        if platform.system() == "Windows":
            os.kill(pid, signal.SIGTERM) # Windows doesn't have SIGKILL
        else:
            os.kill(pid, signal.SIGKILL)
        log(f"Process {pid} terminated instantly.")
    except Exception as e:
        log(f"Failed to kill process {pid}: {e}")

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
            log("Windows Autostart configured in Registry.")
        except Exception as e:
            log(f"Failed to set Windows autostart: {e}")
            
    elif os_name == "Linux":
        import subprocess
        # Use systemd user service for reliable autostart (headless or GUI)
        systemd_user_dir = os.path.expanduser("~/.config/systemd/user")
        os.makedirs(systemd_user_dir, exist_ok=True)
        
        service_file = os.path.join(systemd_user_dir, "vram_guard.service")
        wrapper_script = os.path.join(os.path.dirname(os.path.dirname(script_path)), "scripts", "run_guard.sh")
        log_file = os.path.join(os.path.dirname(os.path.dirname(script_path)), "output.log")
        
        if os.path.exists(wrapper_script):
            content = f"""[Unit]
Description=VRAM Guard - NVIDIA Memory Protection (User Service)
After=network.target

[Service]
Type=simple
ExecStart={wrapper_script}
StandardOutput=append:{log_file}
StandardError=append:{log_file}
Restart=always
RestartSec=3

[Install]
WantedBy=default.target
"""
            try:
                with open(service_file, "w") as f:
                    f.write(content)
                
                # Enable the service
                subprocess.run(["systemctl", "--user", "daemon-reload"], check=True, capture_output=True)
                subprocess.run(["systemctl", "--user", "enable", "vram_guard.service"], check=True, capture_output=True)
                
                log("Linux systemd user service autostart configured successfully.")
                log("Tip: Run 'sudo loginctl enable-linger $USER' to ensure it starts on boot without logging in.")
            except Exception as e:
                log(f"Failed to set up Linux autostart: {e}")
    else:
        log(f"Autostart not supported on {os_name}")

def monitor_vram():
    """Monitor VRAM usage based on config.yaml."""
    # Load config file
    config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.yaml")
    if not os.path.exists(config_path):
        log(f"Error: Config file not found at {config_path}")
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
            
        log(f"Monitoring GPU {gpu_index}: {device_name}")
        
        try:
            mem_info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            total_vram = mem_info.total / (1024 * 1024)
            log(f"Total VRAM: {total_vram:.1f} MB")
        except pynvml.NVMLError as e:
            if "Not Supported" in str(e):
                log("Total VRAM: Unknown (Unified Memory / Not Supported)")
                log("Mode: Per-process monitoring only (sum of process usage)")
                total_vram = float('inf')
            else:
                raise e

        log(f"Threshold: {threshold} MB")
        log(f"Mode: {mode} protection")
        log(f"Interval: {interval}s")
        
        # Check for Unified Memory Architecture (Tegra/Orin/ARM64)
        is_unified = False
        system_baseline = 0
        try:
            if platform.machine() == "aarch64" or "GB10" in device_name or "Tegra" in device_name:
                is_unified = True
                log("Detected Unified Memory Architecture. Enabling System RAM monitoring as fallback.")
                
                # Dynamic Baseline Calibration
                log("Calibrating system baseline (sampling 2s)... ensure system is idle!")
                samples = []
                for _ in range(20):
                    samples.append(psutil.virtual_memory().used / (1024 * 1024))
                    time.sleep(0.1)
                system_baseline = min(samples)
                log(f"Baseline System Memory: {system_baseline:.1f} MB (Offset)")
                log(f"Shield will trigger on: Total System Memory > {threshold} MB")
        except:
            pass
            
        log("-" * 50)
        
        while True:
            try:
                # 1. Get System Memory Stats (Critical for Unified Memory)
                sys_mem = psutil.virtual_memory()
                sys_used_mb = sys_mem.used / (1024 * 1024)
                
                # 2. Get NVML Processes
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                except pynvml.NVMLError:
                    processes = []

                # Check for memory spikes
                total_calculated = 0
                max_vram_proc = None
                max_vram_usage = 0
                max_vram_name = ""
                
                # Create a map of PID -> VRAM usage for sorting
                proc_usage_map = {}

                for proc in processes:
                    if proc.pid in whitelist:
                        continue
                        
                    proc_name = get_process_name(proc.pid)
                    
                    rss_val = get_process_rss_mb(proc.pid)
                    nvml_val = (proc.usedGpuMemory or 0) / (1024 * 1024)
                    
                    # Unified Memory Calculation
                    if is_unified:
                        # On Unified Memory (Grace Hopper/Tegra), GPU allocations often don't show in RSS or NVML.
                        # However, they DO show in Total System Memory.
                        # We use the raw RSS + NVML sum for the process map, but rely on System Total for triggers.
                        vram_used = rss_val + nvml_val
                    else:
                        # Standard Discrete GPU: VRAM is separate
                        vram_used = nvml_val
                        # Fallback to RSS if NVML reports 0 but process is running on GPU (rare but possible)
                        if vram_used == 0 and rss_val > 1000:
                            vram_used = rss_val

                    proc_usage_map[proc.pid] = {
                        'name': proc_name,
                        'usage': vram_used,
                        'rss': rss_val
                    }

                    total_calculated += vram_used
                    
                    # Keep track of largest process
                    if vram_used > max_vram_usage:
                        max_vram_usage = vram_used
                        max_vram_proc = proc.pid
                        max_vram_name = proc_name
                        
                    # PROCESS mode logic
                    if mode.upper() == "PROCESS":
                        if vram_used > threshold:
                            log(f"ALERT: Process '{proc_name}' (PID: {proc.pid}) using {vram_used:.1f} MB (Threshold: {threshold} MB)")
                            if not dry_run:
                                kill_process(proc.pid, proc_name)
                                time.sleep(1) # Let system recover before checking again

                # SYSTEM mode logic
                if mode.upper() == "SYSTEM":
                    # On Unified Memory, use the greater of Calculated VRAM or Actual System RAM Used
                    # This ensures we catch OOM conditions even if our per-process calc is off.
                    effective_total = total_calculated
                    if is_unified:
                        effective_total = sys_used_mb
                        if effective_total > threshold:
                            log(f"SYSTEM ALERT: Total Memory {effective_total:.1f} MB (Baseline {system_baseline:.1f} + Active {(effective_total-system_baseline):.1f}) exceeds {threshold} MB limit!")
                            
                            # If we have a max process from NVML, use it (even if its calculated usage is low)
                            if max_vram_proc:
                                log(f"Killing top GPU consumer '{max_vram_name}' (PID: {max_vram_proc}) - Suspected cause of memory pressure")
                                if not dry_run:
                                    kill_process(max_vram_proc, max_vram_name)
                                    time.sleep(1)
                            # Fallback: If no NVML process found but System RAM is full (Unified OOM)
                            else:
                                # Find top RSS consumer from psutil
                                log(f"High System RAM usage detected (Unified Memory). Scanning for top consumer...")
                                top_pid = None
                                top_rss = 0
                                for p in psutil.process_iter(['pid', 'name', 'memory_info']):
                                    try:
                                        if p.info['pid'] == os.getpid(): continue # Don't kill self
                                        r = p.info['memory_info'].rss / (1024 * 1024)
                                        if r > top_rss:
                                            top_rss = r
                                            top_pid = p.info['pid']
                                            max_vram_name = p.info['name']
                                    except:
                                        continue
                                
                                if top_pid:
                                    log(f"Killing top System RAM consumer '{max_vram_name}' (PID: {top_pid}) using {top_rss:.1f} MB")
                                    if not dry_run:
                                        kill_process(top_pid, max_vram_name)
                                        time.sleep(1)
                        continue # Skip the old logic block

                    if effective_total > threshold:
                        log(f"SYSTEM ALERT: Total Memory {effective_total:.1f} MB exceeds {threshold} MB limit!")
                        
                        # If we have a max process from NVML, use it
                        if max_vram_proc:
                            log(f"Killing top consumer '{max_vram_name}' (PID: {max_vram_proc}) using {max_vram_usage:.1f} MB")
                            if not dry_run:
                                kill_process(max_vram_proc, max_vram_name)
                                time.sleep(1)

            except pynvml.NVMLError as err:
                log(f"NVML Error: {err}")
            
            time.sleep(interval)
            
    except KeyboardInterrupt:
        log("Monitoring stopped.")
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
