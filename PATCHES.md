# Engine changes and attribution

GyroStrata reconstructs [official Strata](https://github.com/Niko1221/Strata) at v0.1.45 (477ac13cbe8e582c20484871ce459d20d82df09d), then applies patches/strata.patch. The full diff changes **48 files** (including tests): **3,619 added lines and 81 removed lines**. Every resulting changed file is hashed in pins.json.

## Imported compatibility

The Gyro author's [Strata integration](https://github.com/agentionai/Strata), including the rc2 work at 9ff02c9fa9c86a88088370925b3c9131cc5d6c26, supplied native trellis quantization and APR/Hadamard support. CPU, GPU, prefill and packing paths must honor those rotations. This is existing public work, not a new quantization algorithm authored here.

The unchanged [agentionai llama.cpp](https://github.com/agentionai/llama.cpp) dependency is pinned at dc255f2a4b6e4211b555b0c05260b2523281f314. It defines the custom tensor types the GGUF needs. Ordinary llama.cpp is not interchangeable.

## Local source changes

- **CPU trellis path:** retained the measured row-construction optimization, with runtime ISA dispatch and numerical parity checks.
- **SSD/CPU overlap:** a persistent async worker fetches file experts while resident experts compute. STRATA_RESIDENT_IO_OVERLAP=1 enables it.
- **RAM placement:** recently used disk experts can replace cold RAM experts after a synchronized reply, without increasing RAM capacity. STRATA_RAM_REBALANCE=512 bounds swaps per reply. Each rewritten RAM place is held from the Foresight swap space while its bytes change (as replace_resident does), so a swap-space copy taken from it is dropped instead of served; a regression test fails without the hold.
- **File-tier skip:** STRATA_FILE_SKIP=R (opt-in; unset leaves the output byte-identical) skips an expert that is in neither VRAM nor the RAM copy when every token of the verify window ranks it R-th or later of its 10 experts (0 = largest weight), the same way STRATA_ROUTE_TAIL_SKIP skips tail experts. Only experts the layer would wait on the SSD for are dropped; RAM experts are still computed. Skipped experts are counted in the engine's existing "route tail skip" log line. The Gyro-M profile uses R=3 with STRATA_ROUTE_TAIL_SKIP=6 (measured on one 12 GB / 32 GB PC: 32K reasoning decode 16 -> 33-37 tok/s; teacher-forced NLL +0.016 on 3,357 tokens).
- **Read merging:** STRATA_IO_MERGE_GAP_KIB exposes the read-gap tradeoff; the selected default remains 1024 KiB.
- **Conversation caching:** explicit tail retention and a near-tail checkpoint reduce rereading when returning to a long prompt. Memory pressure can still evict checkpoints.
- **Suffix policy:** STRATA_LOOKUP_REPROBE_ROUNDS=128 refreshes stale verification costs after expert placement warms; a regression covers an initially unprofitable window.
- **Scheduling/build:** per-request pool-task tuning. UMWAIT (now in upstream Strata) stays off.
- **Blackwell trellis decode:** the CUDA trellis decoder reads its bytes directly; CUDA 13.2 before Update 2 miscompiled the `uint16_t*` form for sm_100 and newer (issue #1).
- **ISA guard:** tools/check_isa_guard.py knows the trellis AVX-512/AVX2 files, so the upstream wide-ISA check covers them.

Supporting readers, packing changes and regression tests are part of the diff. Regenerate it with `git add -A && git diff --cached --binary --full-index <revision>` and do not reformat it.

## Configuration and tools

Adaptive prefill, the 95% prefill VRAM loan, automatic expert caching, Q4 KV, the 32K GPU KV page cache, RAM budgets, partial pinning and CPU/PCIe settings are configuration choices. Some are inherited Strata features; they are not all new engine code.

The interleaved experts.bin groups unchanged native expert bytes for SSD reads. Packing also derives required BF16 projections and records rounding in conversions.json. That conversion is not lossless; the original GGUF, native experts and disk-backed PLE weights are never rewritten.

TUNE.cmd (tune.py, tuning.py) is configuration, not engine code: it measures the existing skip controls and the PCIe share on the user's PC and writes a fingerprinted overlay the launcher applies.

Installation/launch tools add source and binary checks, model/pack validation, capacity checks, profile locks, rollback, safe key removal and process cleanup. They support one Gyro-M text profile. A full standalone Strata fork is optional: the pinned source plus patch reconstructs this engine reproducibly.

The 8192 prefill experiment changed chunk sizing; it was not an expert-cache size change or a whole-engine redesign.

## Experimental AMD installation

The HIP installer builds the same pinned patched source with STRATA_ENABLE_HIP. The model kernels are inherited from that source; this addition supplies HIP toolchain selection, GPU identity, WDDM memory monitoring and parity-gated installation. CUDA and HIP keep separate build files. AMD hardware performance is not yet validated.
