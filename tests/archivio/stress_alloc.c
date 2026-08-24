/* stress_alloc.c - simple memory allocator for VRAM Shield testing.
 * Allocates <MB> MB of system memory (touches it to force physical pages),
 * then sleeps <SECS> seconds. Used to test VRAM Shield SYSTEM-mode trigger
 * on Unified Memory architectures (e.g. NVIDIA GB10).
 *
 * Usage: ./stress_alloc <MB> [SECS] [THREADS]
 */
#define _GNU_SOURCE
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <signal.h>
#include <sys/mman.h>
#include <pthread.h>

static volatile unsigned char *buf = NULL;
static size_t buf_size = 0;
static int n_threads = 1;

static void cleanup(int sig) {
    (void)sig;
    if (buf) munmap((void *)buf, buf_size);
    fprintf(stderr, "\n[stress_alloc] cleaned up after signal %d, freed %zu MB\n",
            sig, buf_size / (1024 * 1024));
    _exit(0);
}

typedef struct {
    unsigned char *start;
    size_t len;
    int tid;
} touch_arg_t;

static void *touch_range(void *arg) {
    touch_arg_t *a = (touch_arg_t *)arg;
    /* Touch every 4 KiB page in this slice */
    volatile unsigned char tmp = 0;
    for (size_t off = 0; off < a->len; off += 4096) {
        tmp ^= a->start[off];
    }
    /* Compiler sink */
    if (tmp == 0xFF) fprintf(stderr, ".");
    fprintf(stderr, "[t%d] done touching %zu MB\n", a->tid, a->len / (1024 * 1024));
    return NULL;
}

int main(int argc, char **argv) {
    if (argc < 2) {
        fprintf(stderr, "Usage: %s <MB> [SECS] [THREADS]\n", argv[0]);
        return 1;
    }
    long mb = atol(argv[1]);
    int secs = (argc > 2) ? atoi(argv[2]) : 30;
    n_threads = (argc > 3) ? atoi(argv[3]) : 8;
    if (n_threads < 1) n_threads = 1;
    if (n_threads > 32) n_threads = 32;
    if (mb <= 0 || mb > 1024L * 1024L) {
        fprintf(stderr, "Invalid MB: %ld\n", mb);
        return 1;
    }

    size_t bytes = (size_t)mb * 1024UL * 1024UL;
    fprintf(stderr, "[stress_alloc] PID %d: requesting %ld MB, %d touch threads, sleep %ds\n",
            getpid(), mb, n_threads, secs);

    /* MAP_POPULATE forces page tables to be set up (pre-faults) */
    buf = mmap(NULL, bytes, PROT_READ | PROT_WRITE,
               MAP_PRIVATE | MAP_ANONYMOUS | MAP_POPULATE, -1, 0);
    if (buf == MAP_FAILED) {
        fprintf(stderr, "[stress_alloc] mmap failed\n");
        return 2;
    }
    buf_size = bytes;

    /* Touch pages in parallel with multiple threads */
    pthread_t threads[32];
    touch_arg_t args[32];
    size_t slice = bytes / n_threads;
    for (int i = 0; i < n_threads; i++) {
        args[i].start = (unsigned char *)buf + i * slice;
        args[i].len = (i == n_threads - 1) ? (bytes - i * slice) : slice;
        args[i].tid = i;
        if (pthread_create(&threads[i], NULL, touch_range, &args[i]) != 0) {
            fprintf(stderr, "[stress_alloc] pthread_create failed for t%d\n", i);
            n_threads = i;
            break;
        }
    }
    for (int i = 0; i < n_threads; i++) {
        pthread_join(threads[i], NULL);
    }
    fprintf(stderr, "[stress_alloc] all %d threads done. memory fully allocated.\n", n_threads);

    /* Hold the memory */
    signal(SIGTERM, cleanup);
    signal(SIGINT, cleanup);
    for (int i = 0; i < secs; i++) {
        sleep(1);
    }
    fprintf(stderr, "[stress_alloc] done without being killed.\n");
    munmap((void *)buf, bytes);
    return 0;
}
