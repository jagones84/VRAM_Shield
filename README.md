# VRAM Shield

**VRAM Shield** is a lightweight, high-performance Python watchdog that monitors NVIDIA GPU memory and protects your machine from OOM crashes. It is specifically optimized for **Unified Memory Architectures** like the **NVIDIA GB10 (DGX Spark, Grace Blackwell)**, where traditional VRAM monitoring returns `N/A` from NVML and you need a system-RAM fallback path.

When the configured memory budget is exceeded, the Shield automatically kills the top consumer process, keeping your interactive session (and the model server feeding it) safe.

---

## Features

- **Unified Memory aware** — automatically falls back to system-RAM monitoring when NVML `memory.total` is `N/A` (e.g. GB10, GH200)
- **Two kill modes**:
  - `PROCESS` — kill specific processes exceeding per-process VRAM
  - `SYSTEM` — kill the top GPU/RSS consumer when total system memory crosses the threshold (recommended for unified memory)
- **Dynamic baseline calibration** — at startup samples 2s of idle system memory and stores the offset so you only count what processes actually use
- **Quick-skip optimization** — when system memory is well below the threshold, the Shield sleeps instead of doing per-process scans (≈0% CPU on idle)
- **PID whitelist** — never kills protected PIDs (default: PID 1 / init)
- **systemd user service** with auto-restart
- **CLI scripts** for start / stop / status

---

## Requirements

- Linux (Ubuntu 22.04+) or Windows
- Python 3.10+
- NVIDIA driver + `libnvidia-ml.so` (or `nvidia-ml-py` wheel for Windows)
- For verification tests: CUDA Toolkit + `gpu-burn` (see [Testing & Verification](#testing--verification))

Python deps (installed automatically by `run_guard.sh`):
- `nvidia-ml-py`
- `psutil`
- `PyYAML`
- `python-dotenv`

---

## Installation

### 1. Clone the Repository
```bash
git clone https://github.com/jagones84/VRAM_Shield.git
cd VRAM_Shield
```

### 2. Run the Installer (one-shot)
The script creates a virtualenv, installs deps, and starts the Shield as a systemd user service.

```bash
./scripts/run_guard.sh
```

On the first run this takes a few seconds to set up `venv/`. Subsequent runs are instant.

---

## Configuration

Edit `config/config.yaml`. To keep machine-specific overrides out of git, use `config/config.local.yaml` (auto-loaded if present).

```yaml
# Default VRAM Threshold in MB
# Examples:
#   113 GB on DGX Spark (GB10, 128 GB unified, ~121 GiB visible)  -> 113000
#   24 GB on RTX 4090 (24 GB dedicated)                            -> 23000
threshold: 113000

# Check interval (seconds)
interval: 0.5

gpu_index: 0
dry_run: false

# Never kill these PIDs
whitelist_pids:
  - 1

# Never kill processes whose name contains any of these substrings.
# Use this for long-running model servers, daemons, and critical services.
# Default: the shield itself, llama.cpp servers, system services.
whitelist_names:
  - llama-server
  - vram_guard
  - systemd
  - init
  - earlyoom

# PROCESS = kill specific processes over their per-process VRAM
# SYSTEM   = kill top consumer when TOTAL system memory > threshold
mode: "SYSTEM"

autostart: true
```

> **Unified Memory note (DGX Spark, GH200, etc.)**
> The GB10 reports `128 GB` of LPDDR5x unified memory. The Linux kernel exposes
> only `~121 GiB` as `MemTotal` in `free` / `/proc/meminfo` (the rest is reserved
> by the firmware). `nvidia-smi --query-gpu=memory.total` returns `N/A` because
> there is no dedicated VRAM. The Shield detects this and switches to
> system-RAM monitoring with the same threshold semantics.
>
> Recommended threshold: **`113000 MB`** (113 GB) — leaves ~8 GB headroom for OS
> + interactive processes on a 128 GB GB10.

---

## Usage

### Status
```bash
./scripts/status_guard.sh
```
Output: `STATUS: VRAM SHIELD IS ACTIVE (PROTECTED)` or `STOPPED (NOT PROTECTED)`, plus the current PID, mode (systemd/manual), and recent log lines.

### Start (manual)
```bash
./scripts/run_guard.sh
```

### Stop
```bash
./scripts/stop_guard.sh
```

### Install as systemd user service (auto-start at login)
```bash
# Copy service file, enable + start
mkdir -p ~/.config/systemd/user
cp scripts/vram_guard.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now vram_guard.service

# Verify
systemctl --user status vram_guard.service
journalctl --user -u vram_guard.service -f
```

> The bundled `scripts/install_service.sh` does the same but installs a **system**
> service in `/etc/systemd/system/` and requires `sudo`. The user-level
> installation above is the recommended path for single-user workstations.

---

## Testing & Verification

This project ships with **one** tool that actually works on DGX Spark (GB10):
`tests/gpu_stress` (custom CUDA kernel: stream triad + FMA, sustained memory
bandwidth + compute). It is the recommended way to load the GPU for trigger
tests and crash reproduction.

> **Why not `gpu-burn`?**
> `gpu-burn`'s `compare.fatbin` kernel triggers `read[0] error 0` on GB10
> (sm_121) and dies at 3-15% on any allocation ≥30 GB. We tried `COMPUTE=121`
> builds and source updates — the comparison kernel still fails. Use
> `gpu_stress` instead. (`tests/gpu_burn` is kept in `tests/archivio/` for
> reference, but do not rely on it for stress tests on Blackwell.)

---

### Project layout (post-cleanup, 2026-08-24)

```
VRAM_shield/
├── src/vram_guard.py           # main watchdog
├── config/config.yaml          # threshold, whitelist, mode
├── scripts/
│   ├── run_guard.sh            # start guard (manual)
│   ├── stop_guard.sh           # stop guard
│   ├── status_guard.sh         # check status
│   ├── install_service.sh      # install systemd service (sudo)
│   ├── vram_guard.service      # systemd user-level unit
│   ├── monitor_realtime.py     # official crash monitor (writes outputs/monitor_*.csv)
│   └── run_stress_test.sh      # launches monitor + gpu_stress together
├── tests/
│   ├── gpu_stress.cu           # source for the stress test
│   ├── gpu_stress              # compiled binary (nvcc, sm_121)
│   └── archivio/               # legacy/archived tests (cuda_alloc, gpu_burn, etc.)
└── outputs/                    # auto-named CSVs from monitor runs
```

---

### 1. Build `gpu_stress` (only once)

```bash
cd /home/jagones/Programs/VRAM_shield/tests
/usr/local/cuda/bin/nvcc -O3 -arch=sm_121 -o gpu_stress gpu_stress.cu
```

- `-arch=sm_121` is mandatory on DGX Spark (GB10). For other GPUs use the
  matching compute capability (`sm_80` A100, `sm_90` H100, `sm_100` B200, ...).
- `nvcc` is at `/usr/local/cuda/bin/nvcc` on DGX. If not in `PATH`, use the
  absolute path.

### 2. `gpu_stress` — sustained GPU + memory stress

`gpu_stress` allocates N MB on the GPU with `cudaMalloc`, commits pages with
`cudaMemset`, then launches a **stream-triad kernel** (`A[i] = B[i] + scalar * C[i]`)
in an infinite loop. The triad pattern forces real memory bandwidth (the
compiler cannot elide it) and FMA saturates the compute units.

```bash
# Manual run
./tests/gpu_stress 105000 1200      # 105 GB, 20 minutes
./tests/gpu_stress 5000 30          # 5 GB smoke test, 30 s
./tests/gpu_stress 110000 0         # 110 GB, run forever (kill with Ctrl-C)
```

What the kernel does each iteration:
1. `B[i]` → register (`load.global`)
2. `A[i] = B[i] + scalar * C[i]` (FMA on register)
3. `__threadfence()` (forces global write)
4. Write back `A[i]`, `B[i]`, `C[i]`

With 48 SMs × 32 blocks × 256 threads = **393 216 threads** active, this
hits >85 W on GB10 and climbs the GPU temperature in minutes.

**WARNING — this WILL heat up the GPU and the LPDDR5x memory.** Do not run
unattended without checking thermals first. Stop the guard (`./scripts/stop_guard.sh`)
before running or the guard will kill `gpu_stress` as soon as it crosses the
threshold.

### 3. Replicating the original physical crash (the goal of this toolset)

The test that previously hard-shut down the DGX Spark (Dashboard reported
~116 GB) used a heavy sustained load. To reproduce it with telemetry:

```bash
# ONE command does everything: starts monitor + stress, waits, kills cleanly.
./scripts/run_stress_test.sh 105000 1200 1
#                              ^MB     ^sec ^Hz
```

This will:
1. Stop the guard (so it doesn't kill `gpu_stress` mid-test)
2. Launch `scripts/monitor_realtime.py` → writes `outputs/monitor_YYYYMMDD_HHMMSS.csv`
   at 1 Hz (GPU temp, power, util, clocks, CPU temp, psutil.used, derived
   Dashboard estimate, OOM count, driver errors, alerts)
3. Launch `tests/gpu_stress 105000 1200` (105 GB, 20 min sustained)
4. After 1200 s, send `SIGINT` to monitor, kill `gpu_stress`, print the CSV path

If the system crashes during the run, the CSV's last rows are your
forensic record. Check, in order:
- `gpu_temp_c` ≥ 95 → thermal emergency
- `gpu_power_w` spike then 0 → driver hang or power event
- `oom_kill_total` increased → kernel OOM-killer ran (unrelated to the Shield)
- `driver_err_30s` > 0 → NVIDIA driver reported errors
- `dashboard_equiv_gb` (auto-computed) → what the NVIDIA Dashboard would show
- `cpu_max_temp_c` ≥ 95 → CPU thermal emergency (LPDDR5x sits on the SoC)

### 4. Triggering the guard (positive test, no crash)

This verifies the guard works at the calibrated threshold. **It is NOT a crash
reproduction** — the guard will kill the stress process before it has time to
overheat anything.

```bash
# Pick a threshold slightly above the load, in psutil.used units
# (Dashboard = psutil.used + 8 GB on GB10; so 120 GB Dashboard ≈ 112 GB psutil)
# Edit config/config.yaml:
#   threshold: 112000
./scripts/run_guard.sh
# In another shell, push past the threshold
./tests/gpu_stress 110000 60
# → expected: "SYSTEM ALERT: Total Memory X exceeds 112000 MB limit!"
#   → "Killing top GPU consumer 'gpu_stress' (PID: ...)"
#   → memory back to baseline
```

### 5. `monitor_realtime.py` (official crash monitor)

`scripts/monitor_realtime.py` is the **only** monitor tool we maintain. It
supersedes the old `tests/monitor_crash.py` (moved to `tests/archivio/`).

```bash
# Default: 2 Hz, auto-named CSV in outputs/
./venv/bin/python3 scripts/monitor_realtime.py

# Explicit rate and path
./venv/bin/python3 scripts/monitor_realtime.py --hz 1 --out /tmp/foo.csv

# Auto-stop after N seconds (good for scripted tests)
./venv/bin/python3 scripts/monitor_realtime.py --hz 1 --duration 600
```

Each run produces a fresh CSV (`monitor_YYYYMMDD_HHMMSS.csv`) — files are
**never overwritten**. Use the most recent file to analyze the latest test.

CSV columns (one row per sample):

| Column | Source | Meaning |
| ------ | ------ | ------- |
| `timestamp` | local clock | ISO datetime with ms |
| `gpu_temp_c` | `nvidia-smi` | Edge temp °C (alert ≥85 warn, ≥93 crit) |
| `gpu_power_w` | `nvidia-smi` | Power draw W |
| `gpu_util_pct` | `nvidia-smi` | SM utilization % |
| `gpu_clock_graph_mhz`, `gpu_clock_sm_mhz` | `nvidia-smi` | Current clocks |
| `gpu_alloc_total_mib` | `pynvml` | Sum of all GPU process allocations (MiB) |
| `cpu_max_temp_c`, `cpu_avg_temp_c` | `/sys/class/thermal` | CPU thermal zones |
| `cpu_avg_freq_mhz`, `cpu_max_freq_mhz` | `/sys/devices/system/cpu` | Current frequencies |
| `sys_mem_total_mib`, `sys_mem_used_mib` | `psutil` | What the Shield watches |
| `sys_mem_pct` | `psutil` | % used (alert ≥95 crit) |
| `dashboard_equiv_mib` | derived | `psutil.used + 8192` (GB10 overhead) |
| `dashboard_equiv_gb` | derived | Same, in GB — matches NVIDIA Dashboard |
| `oom_kill_total` | `/proc/vmstat` | Cumulative OOM-kills since boot |
| `driver_err_30s` | `journalctl`/`dmesg` | Driver errors in last 30 s |
| `top_gpu_pid`, `top_gpu_name`, `top_gpu_used_mib` | `pynvml` | Top GPU consumer at sample time |
| `alert_gpu_thermal`, `alert_cpu_thermal`, `alert_mem_crit` | derived | 1 if threshold crossed, 0 otherwise |

N/A fields (e.g. `gpu_clock_mem_mhz`, `gpu_mem_used_mib` on GB10) are written
as the literal string `N/A` so they don't get confused with real zeros.

### 6. Test results on DGX Spark (sm_121, 128 GB unified, 2026-08-24)

| Test # | Tool              | Size   | Threshold | Outcome |
| ------ | ----------------- | ------ | --------- | ------- |
| 1      | `gpu-burn -m`     | 5 GB   | n/a       | OK (smoke) |
| 2      | `gpu-burn -m`     | 110 GB | 100 GB    | Trigger in 14 s |
| 3      | `gpu-burn -m`     | 60 GB  | n/a       | **Buggy** on GB10 (`compare.fatbin`) |
| 4      | `cuda_alloc`      | 71 GB  | n/a       | OK (memory-only, no compute) |
| 5      | `gpu_stress`      | 5 GB   | n/a       | Smoke: 89 W, 76 °C in 8 s |
| 6      | `gpu_stress`      | 105 GB | 112 GB    | Sustained 40 s @ 89 W, 77 °C, 96 % util (test stopped for monitoring) |
| 7      | `vram_guard`      | idle   | 113 GB    | 0 % CPU (`top` confirmed) |
| 8      | threshold tuning  | 110 GB stress | 112 GB | Guard killed `gpu_stress` in 1 cycle; sys back to 5.5 GB |
| 9      | monitor           | idle+stress | n/a | CSV `outputs/monitor_*.csv` with 25+ columns |

---

## Real-Time Crash Forensics: `crashwatch`

`scripts/crashwatch.sh` is the **persistent, crash-surviving** variant of
`monitor_realtime.py`. Use it when you want a continuous telemetry tape
running on the machine — not tied to a specific test — so that *if* the box
dies you have the last 1–2 seconds of GPU power, GPU temp, CPU temp, memory,
top GPU process, and alerts written to disk before the lights go out.

Differences vs. plain `monitor_realtime.py`:

| | `monitor_realtime.py` | `crashwatch.sh` |
|---|---|---|
| Process supervision | foreground / `nohup` | systemd transient unit `crashwatch.service` (`--user`) |
| Survives kill/restart | no | yes — `Restart=on-failure`, `RestartSec=3` |
| File naming | `monitor_YYYYMMDD_HHMMSS.csv` | `crashwatch_YYYYMMDD_HHMM.csv` (HHMM, no overwrite after restart) |
| Sample rate | 2 Hz default | 1 Hz (less disk I/O, longer tape) |
| Write durability | line-buffered, no fsync | `f.flush()` + `os.fsync()` per row in the script |
| Subcommands | argparse only | `start / stop / status / tail / stats / path / restart` |

It is the recommended background monitor for **OpenClaw** and **Hermes**
workloads (and any other long-running inference / training job on the box):
one row per second, survives process crashes, log file lives in
`outputs/crashwatch_*.csv`.

### Quick start

```bash
# Avvia (idempotente: se gia' attivo, stampa lo stato e basta)
./scripts/crashwatch.sh start

# Stato + path del CSV attivo
./scripts/crashwatch.sh status

# Ultime 20 righe del CSV
./scripts/crashwatch.sh tail

# Statistiche (max/min/avg GPU temp, power, CPU temp) sul CSV attivo
./scripts/crashwatch.sh stats

# Ferma
./scripts/crashwatch.sh stop

# Restart (nuovo file, es. dopo cambio carico)
./scripts/crashwatch.sh restart
```

### Prerequisite: user lingering

`systemd-run --user` richiede che la sessione utente sia "lingering", altrimenti
la unit muore quando termina il login grafico:

```bash
sudo loginctl enable-linger $USER
# verifica
loginctl show-user $USER | grep Linger
# deve stampare Linger=yes
```

### Cosa controllare dopo un crash (in ordine)

Una volta riavviato il DGX, il CSV piu' recente in `outputs/crashwatch_*.csv`
contiene gli ultimi sample prima della morte. Controlla in ordine:

1. `gpu_temp_c` >= 95 -> **thermal emergency GPU**
2. `cpu_max_temp_c` >= 95 -> **thermal emergency CPU / LPDDR5x** (spesso la causa
   su GB10, dove LPDDR5x vive sullo stesso SoC)
3. `gpu_power_w` spike poi 0 -> **driver hang o power event**
4. `oom_kill_total` aumentato -> kernel OOM-killer (non lo Shield, ma rivela
   processi bugiardi)
5. `driver_err_30s` > 0 -> errori del driver NVIDIA nei 30 s precedenti
6. `dashboard_equiv_gb` (auto-computed) -> cosa avrebbe letto la Dashboard NVIDIA
7. `alert_*` = 1 -> quale soglia e' stata superata per prima

### Scope: OpenClaw, Hermes e qualunque carico

`crashwatch` non fa ipotesi sul carico: legge solo da `nvidia-smi`,
`/sys/class/thermal`, `psutil`, `/proc/vmstat`. Quindi va bene come baseline
comune di telemetria per:

- **OpenClaw** (gateway 18789 + adapter multipli)
- **Hermes** (gateway 8642 + WebUI)
- Render ComfyUI / WAN 2.2
- Training / inferenza llama.cpp multi-istanza
- Qualsiasi carico misto CPU+GPU dove vuoi la "scatola nera"

### Esempio di analisi post-crash

```bash
# Identifica il CSV piu' recente
./scripts/crashwatch.sh path
# /home/jagones/Programs/VRAM_shield/outputs/crashwatch_20260909_2323.csv

# Statistiche aggregate del tape
./scripts/crashwatch.sh stats
# samples  = 728
# GPU temp  max 85.0 C  min 52.0 C  avg 69.0 C
# GPU power max 94.61 W min 12.94 W avg 51.90 W
# CPU temp  max 96.2 C  min 63.4 C  avg 82.1 C

# Ultime 5 righe (cosa stava succedendo nell'ultimo secondo)
tail -5 "$(./scripts/crashwatch.sh path)"
# timestamp,epoch_ms,gpu_temp_c,gpu_power_w,...
# 2026-09-09 23:35:36.725,...,79.0,80.85,...
# 2026-09-09 23:35:37.725,...,81.0,73.49,...
# 2026-09-09 23:35:38.725,...,79.0,80.85,...
# 2026-09-09 23:35:39.725,...,81.0,73.49,...
# 2026-09-09 23:35:40.725,...,84.0,81.74,...
```

---


## Architecture Notes: GB10 Unified Memory

The DGX Spark has a single **Grace Blackwell GB10 SoC** with **128 GB of
unified LPDDR5x memory** shared between CPU and GPU. The Linux kernel
exposes ~121 GiB of system RAM; the rest is reserved by firmware/SoC
management. There is no dedicated VRAM, which means the standard
`nvidia-smi --query-gpu=memory.total` field returns `[N/A]`.

### Where each "total" comes from

| Source                            | Value (DGX Spark) | What it actually measures                          |
| --------------------------------- | ----------------- | ------------------------------------------------- |
| `nvidia-smi --query-gpu=memory.total` | `[N/A]`     | Per-GPU dedicated VRAM (none on GB10)             |
| `nvidia-smi --query-gpu=memory.free`  | `[N/A]`     | Free per-GPU VRAM (none on GB10)                  |
| `nvidia-smi -l` from `gpu-burn`  | `130663 MB`       | Total unified memory as seen by the CUDA driver   |
| `psutil.virtual_memory().total`  | `124610.2 MB`     | Total system RAM (Linux kernel perspective)       |
| `free -h` / `/proc/meminfo`      | `121 GiB`         | Same as psutil, in human-readable form            |
| `/proc/meminfo MemTotal`         | `127600812 kB`    | Kernel's `MemTotal` in KiB                        |

`124610 MB` (psutil) vs `130663 MB` (CUDA) is the **firmware/SM management
reservation** of ~6 GB that the OS never sees but the GPU driver does.

### Where the Shield threshold lives

The Shield's `SYSTEM` mode threshold is compared against
`psutil.virtual_memory().used` (i.e. **system memory the kernel considers
actually used**, not GPU-only allocations). On unified memory that equals
the GPU's working set plus OS overhead, so the same number is a faithful
proxy for "VRAM pressure".

The NVIDIA Dashboard, by contrast, reads `nvidia-smi --query-compute-apps`,
which only counts CUDA-context allocations. The **delta between the two is
~7-10 GB** (kernel page cache, buffers, CUDA driver overhead, anonymous
pages outside the GPU mapping). See [§6 of Testing & Verification](#6-vram-cross-check-testsvram_measurepy)
for the measured values.

### Recommended threshold on DGX Spark

**`113000 MB`** (113 GB):
- 128 GB physical − 6 GB firmware reserved − 9 GB OS / kernel / headroom
  ≈ 113 GB safe ceiling
- Equivalent to ~105 GB on the NVIDIA Dashboard `compute_apps` view
- Equivalent to ~110 GiB `free -h` `used`

To change the threshold, edit `config/config.yaml` and either restart the
service (`systemctl --user restart vram_guard.service`) or write the new
value to `config/config.local.yaml` and restart.

---

## Security & Privacy

- `.env` / `.env.*` are ignored by git (except `.env.example`)
- `venv/`, `*.log`, `*.pid` are ignored by git
- `calibration_report*.txt` is ignored by git (machine-specific output)
- No secrets in the repo — `config/config.local.yaml` is for local overrides

Before pushing, verify with:
```bash
git status
git ls-files
```

---

## Repository Structure

```
VRAM_shield/
├── config/
│   ├── config.yaml          # main config (committed)
│   └── config.local.yaml    # local overrides (gitignored)
├── src/
│   └── vram_guard.py        # Shield main loop
├── scripts/
│   ├── run_guard.sh         # entry point (venv + run)
│   ├── stop_guard.sh
│   ├── status_guard.sh
│   ├── install_service.sh   # system-level install (needs sudo)
│   └── vram_guard.service   # user-level systemd unit
├── tests/
│   ├── ramp_up_test.py
│   ├── interactive_calibration.py
│   ├── bench_guard.py       # micro-benchmark of NVML/psutil
│   ├── vram_measure.py      # 7-way VRAM measurement (nvidia-smi, pynvml, psutil, /proc, free)
│   ├── vram_test.sh         # end-to-end test driver (baseline + under_load + cleanup)
│   ├── cuda_alloc.c         # persistent CUDA allocator (recommended on GB10)
│   ├── cuda_alloc           #   compiled binary
│   ├── stress_alloc.c       # system-RAM stress tool
│   └── stress_alloc.py
├── outputs/                 # per-run outputs (gitignored)
├── .env.example
├── .gitignore
├── requirements.txt
└── README.md
```
