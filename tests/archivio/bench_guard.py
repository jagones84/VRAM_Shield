"""Benchmark guard operations to find the CPU hog."""
import time
import pynvml
import psutil

pynvml.nvmlInit()
h = pynvml.nvmlDeviceGetHandleByIndex(0)

N = 200
t = time.time()
for _ in range(N):
    pynvml.nvmlDeviceGetComputeRunningProcesses(h)
print(f"NVML processes:      {(time.time()-t)/N*1000:.2f} ms/call")

t = time.time()
for _ in range(N):
    psutil.virtual_memory()
print(f"psutil virt_mem:     {(time.time()-t)/N*1000:.2f} ms/call")

t = time.time()
for _ in range(5):
    for p in psutil.process_iter(['pid', 'name']):
        pass
print(f"psutil process_iter: {(time.time()-t)/5*1000:.2f} ms/call")

# Combined: what the guard does in quick-skip path
t = time.time()
for _ in range(N):
    psutil.virtual_memory()
    pynvml.nvmlDeviceGetComputeRunningProcesses(h)
print(f"COMBINED (loop):     {(time.time()-t)/N*1000:.2f} ms/call")

pynvml.nvmlShutdown()
