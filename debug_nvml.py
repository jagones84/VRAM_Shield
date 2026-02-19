import pynvml
import psutil
import time

pynvml.nvmlInit()
handle = pynvml.nvmlDeviceGetHandleByIndex(0)
while True:
    try:
        procs = pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
        print(f"[{time.strftime('%H:%M:%S')}] PIDs from NVML: {[p.pid for p in procs]}")
        for p in procs:
            print(f"  PID {p.pid}: memory={p.usedGpuMemory}")
    except Exception as e:
        print(f"Error: {e}")
    time.sleep(1)
