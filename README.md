# GyroStrata - QFN for the desperate

Run **Gyro-M** (Qwen3.8 Flash Next, 256K context) on an ordinary Windows PC with **12 GB VRAM and 32 GB RAM**.
GyroStrata is a patched, pinned build of [Strata](https://github.com/Niko1221/Strata): the model's experts are spread
across VRAM, RAM and the SSD, and the launcher keeps the PC inside safe memory limits.

> **Speed disclaimer.** Measured on my PC (12 GB NVIDIA GPU, 32 GB RAM, PCIe 4.0 NVMe SSD): real reasoning replies
> ran at **about 16 tok/s** with 1.1.0 and run at **33-37 tok/s at 32K context and 30-34 tok/s at 128K** with 1.2.0.
> Your speed depends on your GPU, CPU, RAM and especially your SSD. START-HERE.cmd measures and tunes your PC.

> **This branch (`v0.2.2-port`) is not the Windows release.** Everything below describes GyroStrata 1.2.0, which is
> built on Strata **v0.1.45** and runs on Windows. This branch adds a port of the same engine patch to Strata
> **v0.2.2**, built and measured on **Linux with CUDA**; the Windows installer is untouched.
> See [Strata v0.2.2 on Linux](#strata-v022-on-linux-this-branch) below and
> [V0.2.2-PORT.md](V0.2.2-PORT.md) for the conflict-by-conflict detail.

## Setup in 4 steps

1. **Install the tools** (once; the engine is built on your PC for your GPU):
   [Git](https://git-scm.com/downloads/win),
   [Python 3.12-3.14](https://www.python.org/downloads/windows/),
   [VS 2022 C++ Build Tools](https://aka.ms/vs/17/release/vs_BuildTools.exe) (tick *Desktop development with C++*),
   [CUDA Toolkit 13.2](https://developer.nvidia.com/cuda-toolkit-archive) (Update 2 or later for RTX 50-series) and an
   NVIDIA driver R580 or newer.
2. **Get GyroStrata:** *Code -> Download ZIP* on GitHub and unzip it to a permanent folder, or
   `git clone https://github.com/Gitshop77/GyroStrata.git`. For the ZIP, first right-click it -> *Properties* ->
   tick *Unblock*, so Windows does not stop the setup files as "downloaded from the internet".
3. **Double-click `START-HERE.cmd`** and choose a folder on your SSD for the model. It then does everything:
   - downloads the model (about 86 GiB) in a second window with a progress bar,
   - builds and tests the engine at the same time,
   - installs the model and checks CPU/GPU parity,
   - measures your PC and saves the fastest settings within the quality budget (about 10-15 minutes).

   Expect 1-2 hours in total, mostly the download. If anything stops it, fix what it names and open START-HERE.cmd
   again: finished steps are skipped and the download resumes.
4. **Double-click `Start-Gyro-M-256K.cmd`** in your model folder whenever you want to use the model.

### What you need

- 64-bit Windows, an **AVX2** CPU and an **NVIDIA GPU with 12 GB or more** (compute capability 7.5+).
- **32 GB RAM or more**, with 14 GiB free when the model starts.
- About **125 GiB** free on an SSD for the model and its expert pack, plus 4 GiB for the engine.

More detail: [HARDWARE.md](HARDWARE.md).

### Compatibility

- **NVIDIA (CUDA): supported.** The engine is compiled on your PC for your card. All speeds in this README come from
  my PC; other NVIDIA cards, CPUs, RAM and SSDs have not been measured and will differ.
- **AMD (HIP): experimental, not verified.** Strata supports AMD, and GyroStrata has an AMD install path
  ([AMD.md](AMD.md)) that uses the same engine source, including this release's changes (they contain no CUDA-only
  code). But it has only been tested with simulated hardware: it has not been built or run on a real AMD GPU, so it
  may not work. START-HERE.cmd is NVIDIA-only; AMD users follow AMD.md.
- **The tuner adapts, but is not proven everywhere.** TUNE.cmd measures your own PC, keeps the memory guards on and
  stays within its quality budget for the free RAM it measured with; with less free RAM, or if it cannot run, the
  shipped defaults are used. It has only run on my PC so far.

### Running the steps yourself

START-HERE.cmd chains the same tools you can run one by one (`INSTALL.cmd --help` and `TUNE.cmd --help` list their
options):

```powershell
$ModelDir = "C:\Your Model Folder"
.\DOWNLOAD-MODEL.cmd "$ModelDir"           # the pinned GGUF; resumes, checks SHA256
.\INSTALL.cmd --model-dir "$ModelDir"      # sources, patch, engine build, pack, parity checks, launcher
.\TUNE.cmd --model-dir "$ModelDir"         # optional: measure and save the fastest settings
& "$ModelDir\Start-Gyro-M-256K.cmd"
```

Already have the [pinned GGUF](https://huggingface.co/agentionai/Qwen3.8-Flash-Next-Gyro-GGUF/blob/1ada08422e404aca51ab9df665f089f34c419c6b/Qwen3.8-Flash-Next-Gyro-M-TQ2_0.gguf)?
Put it in the model folder; the download step only checks it. The weights are never modified. Moving the engine or
model folder needs a reinstall.

## Use it

API: **http://127.0.0.1:8080/v1** (OpenAI-compatible) | model: **qwen38-gyro-m** | stop: **Ctrl+C**.

The server listens on **0.0.0.0**, so other devices on your network can reach it. To require a key, run
`INSTALL.cmd --api-key` once (the key is saved in `.gyro-recipe\api-key.txt`); `DELETE-API-KEY.cmd` removes it.

## How it gets its speed

Gyro-M's experts do not fit in 12 GB VRAM + 32 GB RAM, so some are read from the SSD while a reply is written. Waiting
for those reads was more than half of every decode step. This release skips the experts that matter least instead of
waiting for them: of the 10 experts the router picks for each token, the 4 weakest are skipped when they are not in
VRAM, and the 7 weakest when they would have to be read from the SSD:

| Quality level | Settings | Mean NLL change | Use |
|---|---|---:|---|
| exact | no skipping | 0 | identical to 1.1.0's output path |
| **balanced** (default) | STRATA_FILE_SKIP=3, STRATA_ROUTE_TAIL_SKIP=6 | +0.016 | everyday use |
| fast | measured by TUNE.cmd (for example STRATA_FILE_SKIP=2, STRATA_ROUTE_TAIL_SKIP=7) | up to +0.035 | maximum speed |

A mean NLL change of 0.016 is about 1.6% perplexity; the most likely next token is unchanged 90% of the time. Choose a
level with `TUNE.cmd --quality exact|balanced|fast`. The full data and method are in [TUNING.md](TUNING.md).

## Speeds

Measured on my PC: 12 GB NVIDIA GPU, 32 GB RAM, PCIe 4.0 NVMe SSD. Your speeds will differ.

**Reply speed** (long reasoning replies, thinking on):

| Context | v1.1.0 | v1.2.0 |
|---|---:|---:|
| 32K, first reply | 16-17 tok/s | **33-37 tok/s** |
| 32K, follow-up | 15-16 tok/s | **33-35 tok/s** |
| 128K, first reply | 16 tok/s | **32-34 tok/s** |
| 128K, follow-up | stopped (out of RAM) | **30-32 tok/s** |

**Prompt reading and first token** (v1.2.0):

| Prompt length | Reading speed | First token, new prompt | First token, same prompt again |
|---|---:|---:|---:|
| 8K | 877 tok/s | 9.4 s | 0.2 s |
| 32K | 1,282 tok/s | 25.6 s | 0.3 s |
| 64K | 1,448 tok/s | 45.3 s | 0.5 s |
| 128K | 1,577 tok/s | 83.2 s | 0.6 s |
| 192K | 1,598 tok/s | 123.1 s | 0.7 s |
| About 256K | 1,589 tok/s | 164.4 s | 0.9 s |


## Safety limits

- The launcher stops the model if GPU memory passes **min(11.5 GiB, the card's memory minus 512 MiB)** or available RAM
  falls below **512 MiB**. Sampling can miss very short spikes.
- Default VRAM reserve 1216 MiB; conversation cache 3 GiB on 32 GB RAM (4 GiB from 48 GB).
- Q4 KV cache and the BF16 pack conversions have small precision costs; expert skipping has the measured cost above.
- MTP and vision are off. Thinking is on without a budget; earlier thinking is removed from the history.
- The 32K GPU cache does **not** limit attention to 32K. Leave room for the reply within 256K.

## Strata v0.2.2 on Linux (this branch)

A port of the engine patch to [Strata v0.2.2](https://github.com/Niko1221/Strata), built with CUDA and measured on
Linux. It is published as `patches/strata-022.patch` (19 files, +383/-19) and applies the same way the v0.1.45
reconstruction does. Start-Here, the tuner and the Windows tools are **not** part of this path.

### Build it

```sh
git clone https://github.com/Niko1221/Strata.git && cd Strata
git checkout v0.2.2
git apply --3way /path/to/GyroStrata/patches/strata-022.patch    # 15 files conflict, see below

cmake -B build -DCMAKE_BUILD_TYPE=Release -DSTRATA_ENABLE_CUDA=ON \
      -DCMAKE_CUDA_ARCHITECTURES=89 -DSTRATA_GGML_DIR=/path/to/llama.cpp
cmake --build build -j"$(nproc)"
```

`STRATA_GGML_DIR` **must** be the [agentionai llama.cpp fork](https://github.com/agentionai/llama.cpp) at
`dc255f2a4b6e4211b555b0c05260b2523281f314`. An upstream ggml has no TQ2_T / TQK6 / TQK7 types, and v0.2.2's
native pack path refuses the model without them. With the fork, the trellis MMQ instances come from its own
`mmq-instance-tqk6.cu` and `STRATA_MMQ_TQ=1` is set automatically.

### What conflicts, and why

`git apply --3way` conflicts in **15 files**, not four, because v0.2.2 moved ahead of the v0.1.45 patch. v0.2.2 wins
wherever it is a superset, and the patch's intent is re-applied on top:

- `src/core/expert_source.cpp` — v0.2.2's `STRATA_COLD_OVERLAP` replaces the patch's Windows-only
  `STRATA_RESIDENT_IO_OVERLAP`; `STRATA_FILE_SKIP`, `ram_heat` and `rebalance_ram` are ported onto it. Taking the
  v0.2.2 side leaves three dangling references (`prepare_jobs`, `ready_jobs`, `ready_ms`) to revert.
- `src/kernels/cuda/iq_kernels.cu` — 13 conflicts, all v0.2.2 supersets. **The 3-way merge duplicates
  `hadamard_rows_kernel`** (17 lines defined twice, five nvcc errors); delete the second copy.
- `tq_avx2.cpp` keeps the patch's `rows4<KB>` TQ2_T fast path inside v0.2.2's body; `tq_cpu*` and `native_expert.cpp`
  keep v0.2.2's `STRATA_TQ_X86` guards; `CMakeLists.txt` keeps v0.2.2's `STRATA_MMQ_TQ_OVERLAY` and
  `SKIP_RETURN_CODE 77`.

### Settings that work, and what they cost

128K context, `--kv q4_0 --kv-resident 20480`, `--resident-budget-gib 16`, `--expert-cache 2688
--expert-cache-per-layer`, `--prefill auto`, the drafter on (`--mtp <mtp>/rt`), `STRATA_FILE_SKIP=3`,
`STRATA_ROUTE_TAIL_SKIP=6`, one slot.

| What | Measured |
|---|---|
| Reply speed, real traffic (this branch) | **26-28 tok/s** |
| Reply speed, drafter off | 9.6 tok/s |
| Reply speed, predictable continuation + drafter | 21.9 tok/s (52% draft acceptance) |
| Prompt reading | ~25 tok/s |
| First token | ~20 s (the 16 GiB resident copy; about 0.75 s per GiB) |
| Expert-cache hit rate | 65-85% |
| VRAM | 10.6 of 12.3 GB |

Five things this port found in the shipped setup, all measured:

1. **`profiles/M.json` passes no `--mtp`.** `--spec` only sizes the verify window; without `--mtp` no draft layer
   loads and every draft is rejected. That is 9.6 tok/s instead of ~27 on real traffic, with identical output.
2. **`--expert-cache auto` is not reproducible** — it sizes from whatever VRAM is free at start. The same config gave
   2,688 slots on one start and 1,719 on the next. Pin the count.
3. **`--parallel 2` costs 0.94 GiB** of expert-cache VRAM ("the slot sessions take 0.94 GiB of VRAM on CUDA0 that the
   expert cache would otherwise hold"). One user: `--parallel 1` returns about 750 slots.
4. **The drafter costs 945 MiB** (820 draft layer + 125 draft head) and is worth about 2.8x. Keep it.
5. **`--resident-budget-gib 12` is strictly dominated** — the same decode as 8 GiB, 3.5 s slower to start.

### Limits

Not tested on Blackwell (v0.2.2's `uint16_t` TQ2_T reads are kept over the patch's byte-load workaround; the target
is sm_89). `tq_avx512.cpp` compiles but never ran — the test CPU has no AVX-512, though `tq_cpu_parity` passes
bit-for-bit for scalar and AVX2 against ggml-cpu's `vec_dot` (~1e-7 relative). HIP, Metal and SYCL were not built.
256K context moves the KV to pinned RAM and costs about 1.3 GiB of cache slots; 128K is what fits comfortably.

## Documentation

- [TUNING.md](TUNING.md) - the speed recipe, measurements and how TUNE.cmd works
- [HARDWARE.md](HARDWARE.md) - hardware policy and manual controls
- [PATCHES.md](PATCHES.md) - engine changes and attribution
- [V0.2.2-PORT.md](V0.2.2-PORT.md) - the Strata v0.2.2 port on this branch (conflicts, build, measurements)
- [UPDATING.md](UPDATING.md) - updates and rollback
- [AMD.md](AMD.md) - experimental AMD/HIP installation
- [CHANGELOG.md](CHANGELOG.md) - release history

## Changelog

- **1.2.0:** about twice the real reasoning speed (expert skipping), one-click START-HERE.cmd, TUNE.cmd and TUNING.md, a VRAM reserve fix for 12 GB
  cards, a RAM fix for long two-turn conversations on 32 GB, and an engine race fix.
- **1.1.0:** Strata v0.1.45, RTX 50-series fix, downloader fix, experimental AMD/HIP build.
- **1.0.0:** native Gyro trellis/Hadamard support, CPU/SSD optimizations, verification, guards and rollback.

## Reporting slow speeds

Open an issue with your GPU and VRAM, CPU, RAM size and speed, SSD model, Windows/driver/engine version, backend,
context and settings, `.gyro-recipe\tune\last-run.txt` if you ran TUNE.cmd, and the prefill/output tok/s you see.
Keep private prompts out of logs.
