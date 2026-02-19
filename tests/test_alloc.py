import torch
import time
print("Allocating 10GB...")
try:
    x = torch.zeros((10000, 1024, 1024), dtype=torch.uint8, device='cuda')
    print("Allocated.")
    time.sleep(10)
except Exception as e:
    print(e)
