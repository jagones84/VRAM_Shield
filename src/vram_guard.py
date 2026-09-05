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

# Process names that should NEVER be killed - killing these would crash the system,
# the user session, network stack, GPU drivers, or our own watchdog.
# Rule of thumb: only kill user-level GPU compute jobs (python, java, etc.)
SAFE_PROCESS_NAMES = {
    # Kernel / init
    'init', 'systemd', 'kthreadd', 'kworker', 'rcu_sched', 'rcu_bh',
    'migration', 'ksoftirqd', 'cpuhp', 'kdevtmpfs', 'netns', 'kblockd',
    'crypto', 'kthread', 'irq', 'scsi', 'ata_sff', 'kmodule',
    'writeback', 'kintegrityd', 'kpagecache', 'khvcd', 'kauditd',
    # SSH / remote access
    'sshd', 'ssh', 'sudo', 'su', 'cron', 'crond', 'anacron', 'atd',
    # Display / session
    'gdm', 'gdm3', 'gdm-session-worker', 'gnome-shell', 'gnome-session',
    'gnome-session-binary', 'Xorg', 'Xwayland', 'mutter', 'mutter-x11-fram',
    'kwin_wayland', 'kwin_x11', 'wayland', 'weston',
    # Network
    'NetworkManager', 'wpa_supplicant', 'dhclient', 'systemd-resolved',
    'systemd-networkd', 'iwd', 'avahi-daemon', 'wpa_actiond',
    # D-Bus / login
    'dbus-daemon', 'dbus-broker', 'systemd-logind', 'systemd-udevd',
    # Containers (would break user's running services)
    'containerd', 'containerd-shim', 'dockerd', 'docker-proxy',
    # Mellanox / NIC tools (would degrade network further)
    'mstflint', 'mstconfig', 'ibdev2netdev', 'perfquery', 'ibstat',
    'mstprivhost', 'mlnx_tune', 'iblinkinfo', 'ibqueryerrors',
    # NVIDIA core services
    'nvidia-dgx-telemetry', 'nvidia-smi', 'nvidia-cuda-mps',
    'nvidia-persistenced', 'nvidia-cuda-mps-control',
    'nvidia-modprobe', 'nvidia-powerd', 'nvidia-smi.pid',
    # System services
    'snapd', 'packagekitd', 'polkitd', 'accounts-daemon',
    'systemd-journald', 'systemd-tmpfiles', 'systemd-coredump',
    'upowerd', 'thermald', 'power-profiles-daemon',
    'pulseaudio', 'wireplumber', 'pipewire',
    'fwupd', 'fwupdated',
    # Self-protection
    'vram_guard', 'run_guard.sh',
    # Shells and utilities (avoid killing user shell mid-session)
    'bash', 'sh', 'zsh', 'fish', 'dash', 'ksh',
    # Our own python interpreter
    'python3', 'python',
    # EDGE / GPU driver userspace that may hold critical handles
    'nvidia-ctk', 'nvidia-container-cli', 'nvidia-container-runtime',
    # Cron / anacron
    'cron', 'anacron',
}

# Process user-names that are always safe (system-owned)
SAFE_USERNAMES = {
    'root', 'gdm', 'systemd-network', 'systemd-resolve',
    'systemd-timesync', 'syslog', 'messagebus', 'avahi',
    'daemon', 'nobody', '_apt', 'snap_daemon',
}

# Never kill PIDs below this (kernel threads, init)
KERNEL_PID_LIMIT = 200


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
    """Fallback: get the Resident Set Size (RSS) in MB from the OS for a given PID."""
    try:
        proc = psutil.Process(pid)
        return proc.memory_info().rss / (1024 * 1024)
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return 0


def get_process_username(pid):
    """Get username owning the process. Returns 'Unknown' on error."""
    try:
        proc = psutil.Process(pid)
        return proc.username()
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
        return "Unknown"


def is_safe_to_kill(pid, name, whitelist, self_pid, name_whitelist=None):
    """Check whether it is safe to kill the given process.

    Returns (True, "ok") if safe to kill, otherwise (False, reason).
    Multiple safeguards are applied to avoid killing system-critical processes.
    """
    if pid == self_pid:
        return False, "self"
    if pid < KERNEL_PID_LIMIT:
        return False, f"kernel PID (<{KERNEL_PID_LIMIT})"
    if pid in whitelist:
        return False, "user whitelist"
    # Check name whitelist (substring match from config)
    if name_whitelist:
        for protected in name_whitelist:
            if protected and protected in name:
                return False, f"name whitelist: '{protected}'"
    if name in SAFE_PROCESS_NAMES:
        return False, f"protected process: {name}"
    # Match wildcard patterns (e.g. 'kworker/*' -> SAFE_PROCESS_NAMES 'kworker*')
    for safe in SAFE_PROCESS_NAMES:
        if safe.endswith('*') and name.startswith(safe[:-1]):
            return False, f"protected process pattern: {safe}"
    username = get_process_username(pid)
    # Strip domain prefix if present (e.g. 'JAGONES\\jagones' -> 'jagones')
    if '\\' in username:
        username = username.split('\\', 1)[1]
    if username in SAFE_USERNAMES:
        return False, f"protected user: {username}"
    return True, "ok"


def kill_process(pid, process_name):
    """Forcefully and instantly kill a process using SIGKILL."""
    log(f"!!! KILLING process {process_name} (PID: {pid}) !!!")
    try:
        if platform.system() == "Windows":
            os.kill(pid, signal.SIGTERM)  # Windows doesn't have SIGKILL
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
            cmd = f'pythonw.exe "{script_path}"'
            winreg.SetValueEx(key, app_name, 0, winreg.REG_SZ, cmd)
            winreg.CloseKey(key)
            log("Windows Autostart configured in Registry.")
        except Exception as e:
            log(f"Failed to set Windows autostart: {e}")

    elif os_name == "Linux":
        import subprocess
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
    if config is None:
        config = {}

    local_config_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config", "config.local.yaml")
    if os.path.exists(local_config_path):
        with open(local_config_path, 'r') as f:
            local_config = yaml.safe_load(f) or {}
        if isinstance(local_config, dict):
            config.update(local_config)

    # Defaults chosen to be VERY conservative on a 128GB DGX Spark:
    #   - threshold: 127000 MB (127 GB) - leaves only 1 GB headroom, never trigger
    #     unless the user is running an extreme workload that truly needs to be killed.
    #   - interval: 5.0 s - reduces CPU usage by 10x vs the original 0.5 s.
    threshold = config.get('threshold', 127000)
    interval = config.get('interval', 5.0)
    gpu_index = config.get('gpu_index', 0)
    dry_run = config.get('dry_run', False)
    whitelist = config.get('whitelist_pids', [])
    mode = config.get('mode', 'PROCESS')
    autostart = config.get('autostart', False)

    self_pid = os.getpid()

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
        log(f"Safe-PID limit: < {KERNEL_PID_LIMIT} (never killed)")

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
        except Exception:
            pass

        log("-" * 50)

        # Quick-skip threshold: when system memory is well below the kill threshold,
        # we skip the expensive per-process scan and just sleep.
        quick_skip_ratio = 0.80
        quick_skip_threshold = threshold * quick_skip_ratio

        # Cycle counter for periodic slow diagnostic log
        cycle_count = 0

        while True:
            cycle_count += 1
            try:
                # 1. Get System Memory Stats (Critical for Unified Memory)
                sys_mem = psutil.virtual_memory()
                sys_used_mb = sys_mem.used / (1024 * 1024)

                # 2. Get NVML Processes
                try:
                    processes = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
                except pynvml.NVMLError:
                    processes = []

                # OPTIMIZATION: if system memory is well below threshold, skip the
                # expensive per-process analysis and just sleep. This dramatically
                # reduces CPU usage during normal operation.
                if is_unified and sys_used_mb < quick_skip_threshold:
                    if cycle_count % 60 == 0:  # log every 5 minutes
                        log(f"OK: sys_used={sys_used_mb:.0f}MB (limit {threshold}MB) - {len(processes)} GPU procs tracked, idle")
                    time.sleep(interval)
                    continue

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
                        vram_used = rss_val + nvml_val
                    else:
                        vram_used = nvml_val
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
                            safe, reason = is_safe_to_kill(proc.pid, proc_name, whitelist, self_pid)
                            if not safe:
                                log(f"PROTECT: skipping kill of '{proc_name}' (PID: {proc.pid}) - {reason}")
                            elif not dry_run:
                                kill_process(proc.pid, proc_name)
                                time.sleep(1)  # Let system recover before checking again

                # SYSTEM mode logic
                if mode.upper() == "SYSTEM":
                    effective_total = total_calculated
                    if is_unified:
                        effective_total = sys_used_mb
                        if effective_total > threshold:
                            log(f"SYSTEM ALERT: Total Memory {effective_total:.1f} MB (Baseline {system_baseline:.1f} + Active {(effective_total-system_baseline):.1f}) exceeds {threshold} MB limit!")

                            # If we have a max process from NVML, use it (even if its calculated usage is low)
                            if max_vram_proc:
                                safe, reason = is_safe_to_kill(max_vram_proc, max_vram_name, whitelist, self_pid)
                                if not safe:
                                    log(f"PROTECT: skipping kill of '{max_vram_name}' (PID: {max_vram_proc}) - {reason}")
                                else:
                                    log(f"Killing top GPU consumer '{max_vram_name}' (PID: {max_vram_proc}) - Suspected cause of memory pressure")
                                    if not dry_run:
                                        kill_process(max_vram_proc, max_vram_name)
                                        time.sleep(1)
                            else:
                                # Fallback: scan all processes for top RSS consumer
                                log(f"High System RAM usage detected (Unified Memory). Scanning for top consumer...")
                                top_pid = None
                                top_rss = 0
                                for p in psutil.process_iter(['pid', 'name', 'memory_info']):
                                    try:
                                        pid_i = p.info['pid']
                                        if pid_i == self_pid:
                                            continue
                                        name_i = p.info['name']
                                        r = p.info['memory_info'].rss / (1024 * 1024)
                                        safe, reason = is_safe_to_kill(pid_i, name_i, whitelist, self_pid)
                                        if not safe:
                                            continue
                                        if r > top_rss:
                                            top_rss = r
                                            top_pid = pid_i
                                            max_vram_name = name_i
                                    except Exception:
                                        continue

                                if top_pid:
                                    log(f"Killing top System RAM consumer '{max_vram_name}' (PID: {top_pid}) using {top_rss:.1f} MB")
                                    if not dry_run:
                                        kill_process(top_pid, max_vram_name)
                                        time.sleep(1)
                        continue  # Skip the old logic block

                    if effective_total > threshold:
                        log(f"SYSTEM ALERT: Total Memory {effective_total:.1f} MB exceeds {threshold} MB limit!")

                        if max_vram_proc:
                            safe, reason = is_safe_to_kill(max_vram_proc, max_vram_name, whitelist, self_pid)
                            if not safe:
                                log(f"PROTECT: skipping kill of '{max_vram_name}' (PID: {max_vram_proc}) - {reason}")
                            else:
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
