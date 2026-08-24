"""Stress allocator for VRAM Shield testing - allocates N MB on CUDA."""
import sys
import os
import time
import signal

def main():
    target_mb = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
    duration = int(sys.argv[2]) if len(sys.argv) > 2 else 30
    pid = os.getpid()
    print(f"[{pid}] Allocating {target_mb} MB on GPU for {duration}s", flush=True)
    try:
        import torch
        n = target_mb * 1024 * 1024 // 4  # float32
        x = torch.zeros(n, dtype=torch.float32, device='cuda')
        print(f"[{pid}] Allocated {x.element_size()*x.nelement()/(1024*1024):.0f} MB", flush=True)
        # Touch memory to actually allocate
        x.fill_(0.5)
        end = time.time() + duration
        while time.time() < end:
            x.fill_(0.5)
            time.sleep(0.5)
        print(f"[{pid}] Done without being killed.", flush=True)
    except KeyboardInterrupt:
        print(f"[{pid}] Interrupted", flush=True)

if __name__ == "__main__":
    main()
