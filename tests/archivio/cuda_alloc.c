// cuda_alloc.c — persistent CUDA memory allocator for nvidia-smi dashboard testing.
// Usage: ./cuda_alloc <MB> [touch]
//   MB    : megabytes to allocate on the (unified) GPU
//   touch : if set, write 0xAA to every 4 KiB page so the allocation is
//           resident (some allocators lazy-commit on first write)
//
// The process then loops until killed, so nvidia-smi --query-compute-apps
// can see it from another shell / the NVIDIA Dashboard.

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cuda_runtime.h>
#include <signal.h>
#include <unistd.h>

static volatile int keep_running = 1;

static void handle_sig(int sig) {
    (void)sig;
    keep_running = 0;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <MB> [touch]\n", argv[0]);
        return 1;
    }
    long mb = atol(argv[1]);
    int touch = (argc >= 3);
    if (mb <= 0 || mb > 200000) {
        fprintf(stderr, "MB must be in (0, 200000], got %ld\n", mb);
        return 1;
    }
    size_t bytes = (size_t)mb * 1024 * 1024;

    signal(SIGINT, handle_sig);
    signal(SIGTERM, handle_sig);

    cudaError_t err = cudaSetDevice(0);
    if (err != cudaSuccess) {
        fprintf(stderr, "cudaSetDevice failed: %s\n", cudaGetErrorString(err));
        return 1;
    }

    void *ptr = NULL;
    fprintf(stderr, "[cuda_alloc] requesting %ld MB (%zu bytes) on device 0...\n", mb, bytes);
    err = cudaMalloc(&ptr, bytes);
    if (err != cudaSuccess) {
        fprintf(stderr, "[cuda_alloc] cudaMalloc failed: %s\n", cudaGetErrorString(err));
        return 1;
    }
    fprintf(stderr, "[cuda_alloc] allocated at %p, pid=%d\n", ptr, getpid());

    if (touch) {
        fprintf(stderr, "[cuda_alloc] touching memory via cudaMemset...\n");
        // cudaMemset is one driver call (vs millions of host writes)
        // and lets the driver fault-in pages as needed.
        err = cudaMemset(ptr, 0xAA, bytes);
        if (err != cudaSuccess) {
            fprintf(stderr, "[cuda_alloc] cudaMemset failed: %s\n", cudaGetErrorString(err));
            cudaFree(ptr);
            return 1;
        }
        err = cudaDeviceSynchronize();
        if (err != cudaSuccess) {
            fprintf(stderr, "[cuda_alloc] cudaDeviceSynchronize failed: %s\n", cudaGetErrorString(err));
            cudaFree(ptr);
            return 1;
        }
        fprintf(stderr, "[cuda_alloc] touch complete.\n");
    }

    fprintf(stderr, "[cuda_alloc] holding allocation. PID=%d, send SIGTERM to free.\n", getpid());
    fflush(stderr);

    // Idle loop: keep the process alive so nvidia-smi / NVIDIA Dashboard
    // can see the allocation. Every 30s print a heartbeat.
    int n = 0;
    while (keep_running) {
        sleep(30);
        n++;
        fprintf(stderr, "[cuda_alloc] heartbeat #%d (alive)\n", n);
        fflush(stderr);
    }

    fprintf(stderr, "[cuda_alloc] freeing %p\n", ptr);
    cudaFree(ptr);
    cudaDeviceReset();
    return 0;
}
