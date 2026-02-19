import pynvml
pynvml.nvmlInit()
handle = pynvml.nvmlDeviceGetHandleByIndex(0)
procs = []
try:
    procs += pynvml.nvmlDeviceGetComputeRunningProcesses(handle)
except pynvml.NVMLError as e:
    print(f"Compute error: {e}")
try:
    procs += pynvml.nvmlDeviceGetGraphicsRunningProcesses(handle)
except pynvml.NVMLError as e:
    print(f"Graphics error: {e}")
for p in procs:
    print(f"PID: {p.pid}, Memory: {p.usedGpuMemory}")
pynvml.nvmlShutdown()
