// gpu_stress.cu — sustained GPU stress: memory bandwidth + FMA compute.
// Bypasses gpu-burn's broken compare.fatbin kernel on GB10 (sm_121).
// Lancia kernel in loop async (no sync) per tenere GPU sempre busy.
//
// Usage: ./gpu_stress <MB> [seconds]
//   MB      : megabytes to allocate (resident, touched)
//   seconds : run duration in seconds (0 = forever, default 1200)

#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <cuda_runtime.h>
#include <signal.h>
#include <unistd.h>
#include <time.h>

static volatile int keep_running = 1;

static void handle_sig(int sig) {
    (void)sig;
    keep_running = 0;
}

// Kernel "rovente": stream triad (A = B + s*C) + FMA.
// Il pattern triad costringe il compilatore a fare le letture e la scrittura
// in memoria globale. Aggiungiamo FMA in loop per massimizzare il compute.
// Tutti i 3 buffer sono allocati nello stesso puntatore (diviso in 3).
__global__ void burn_kernel(
    float* __restrict__ A,
    float* __restrict__ B,
    float* __restrict__ C,
    float scalar,
    long long n,
    int iters
) {
    long long i = (long long)blockIdx.x * blockDim.x + threadIdx.x;
    if (i >= n) return;

    // Carica B[i] e C[i] in registri (1 sola volta)
    float b = B[i];
    float c = C[i];

    // Loop: A[i] = b + scalar*c, con FMA aggiuntivi
    for (int k = 0; k < iters; k++) {
        b = fmaf(c, scalar, b);    // FMA: b = b + scalar*c
        b = fmaf(b, 1.0001f, 0.0001f);  // FMA extra
        c = fmaf(b, 0.9999f, c);    // C update
    }

    // Scrivi A[i] in memoria globale. Il pattern triad costringe la scrittura
    // (il compilatore non puo' elidere perche' A[i] potrebbe essere letto da altri).
    A[i] = b;
    B[i] = b;  // forza write-back di B
    C[i] = c;  // forza write-back di C
    __threadfence();
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <MB> [seconds]\n", argv[0]);
        return 1;
    }
    long mb = atol(argv[1]);
    int seconds = (argc >= 3) ? atoi(argv[2]) : 1200;
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
    fprintf(stderr, "[gpu_stress] requesting %ld MB on device 0...\n", mb);
    err = cudaMalloc(&ptr, bytes);
    if (err != cudaSuccess) {
        fprintf(stderr, "cudaMalloc failed: %s\n", cudaGetErrorString(err));
        return 1;
    }
    fprintf(stderr, "[gpu_stress] allocated at %p, pid=%d\n", ptr, getpid());

    err = cudaMemset(ptr, 0xAA, bytes);
    if (err != cudaSuccess) {
        fprintf(stderr, "cudaMemset failed: %s\n", cudaGetErrorString(err));
        cudaFree(ptr);
        return 1;
    }
    err = cudaDeviceSynchronize();
    if (err != cudaSuccess) {
        fprintf(stderr, "cudaDeviceSynchronize failed: %s\n", cudaGetErrorString(err));
        cudaFree(ptr);
        return 1;
    }
    fprintf(stderr, "[gpu_stress] touch complete. starting kernel loop.\n");

    int dev = 0;
    cudaDeviceProp prop;
    cudaGetDeviceProperties(&prop, dev);
    int sms = prop.multiProcessorCount;
    fprintf(stderr, "[gpu_stress] GPU: %s, %d SMs, %zu KB shmem/SM\n",
            prop.name, sms, prop.sharedMemPerMultiprocessor / 1024);

    // Saturazione aggressiva:
    // 32 blocchi per SM = 1536 blocchi su 48 SMs
    // 256 threads per blocco = 393216 threads totali
    int threads = 256;
    int blocks = sms * 32;
    int iters_per_thread = 100000;  // pesante: ~1-2s per kernel
    // Dividi il buffer in 3 parti: A, B, C
    long long n_per = (long long)mb * 1024 * 1024 / sizeof(float) / 3;
    long long total_n = n_per * 3;
    float* base = (float*)ptr;
    float* A = base;
    float* B = base + n_per;
    float* C = base + 2 * n_per;
    float scalar = 1.2345f;

    fprintf(stderr, "[gpu_stress] launching %d blocks x %d threads, %d iters, n_per=%lld floats (A,B,C)\n",
            blocks, threads, iters_per_thread, n_per);
    fflush(stderr);

    time_t start = time(NULL);
    long long n_kernels = 0;
    while (keep_running) {
        burn_kernel<<<blocks, threads>>>(A, B, C, scalar, n_per, iters_per_thread);
        err = cudaGetLastError();
        if (err != cudaSuccess) {
            fprintf(stderr, "kernel launch error: %s\n", cudaGetErrorString(err));
            break;
        }
        n_kernels++;
        // Sync per sapere se ha finito
        err = cudaDeviceSynchronize();
        if (err != cudaSuccess) {
            fprintf(stderr, "sync error: %s\n", cudaGetErrorString(err));
            break;
        }
        time_t now = time(NULL);
        int elapsed = (int)(now - start);
        if (seconds > 0 && elapsed >= seconds) break;
        if (n_kernels % 5 == 0) {
            fprintf(stderr, "[gpu_stress] %lld kernels, %ds elapsed, alloc=%ldMB\n",
                    n_kernels, elapsed, mb);
            fflush(stderr);
        }
    }

    fprintf(stderr, "[gpu_stress] stopping. total kernels: %lld\n", n_kernels);
    cudaDeviceSynchronize();
    fprintf(stderr, "[gpu_stress] freeing %p\n", ptr);
    cudaFree(ptr);
    cudaDeviceReset();
    return 0;
}
