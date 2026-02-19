import sys
import psutil
import time
import ctypes

# Allocate 10GB but don't touch it
size = 10 * 1024**3
buf = ctypes.create_string_buffer(size)

p = psutil.Process()
mem = p.memory_info()
print(f"Allocated 10GB virtual memory.")
print(f"RSS: {mem.rss / 1024**2:.1f} MB | VMS: {mem.vms / 1024**2:.1f} MB")
