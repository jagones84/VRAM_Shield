import sys
import psutil
import time
import mmap

# Allocate 10GB virtually without touching
size = 10 * 1024**3
buf = mmap.mmap(-1, size)

p = psutil.Process()
mem = p.memory_info()
print(f"Allocated 10GB virtual memory.")
print(f"RSS: {mem.rss / 1024**2:.1f} MB | VMS: {mem.vms / 1024**2:.1f} MB")
