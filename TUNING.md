# Tuning Gyro-M for speed

This page explains how GyroStrata gets its speed and how TUNE.cmd measures it. It records the recipe that took my
12 GB / 32 GB PC from **about 16 to 33-37 output tok/s on real reasoning** (32K context), how it was measured, and how to repeat it.

## The short version

1. **START-HERE.cmd already tunes your PC** as its last step (about 10-15 minutes). Without tuning, the shipped profile
   uses the recipe below, which is the result on my PC.
2. To measure again (new hardware, more RAM, or another quality level), run **TUNE.cmd**:

   ```powershell
   .\TUNE.cmd --quality balanced          # exact | balanced (default) | fast
   ```

   It writes `.gyro-recipe\M.tune.json` beside your weights; the launcher applies it on every start and prints
   `tuning: ...`. Delete the file to go back to the profile's defaults. `--quick` skips steps 2-3 below (about 7 minutes),
   `--thorough` measures all nine settings and re-reads the three leaders twice (slower), `--confirm` adds a real reply.

## What TUNE.cmd does

1. **The settings that can win on your PC, once each.** Skipping off is read first: it is the quality reference, and
   the engine's start-up log tells whether experts spill to the SSD. If they do, five file-skip settings follow (file 3,
   file 3 + tail 7, file 3 + tail 6, file 2 + tail 7, file 2 + tail 6); if every expert fits in VRAM + RAM, the file skip
   has nothing to skip and four tail-skip settings follow instead. Each setting starts the engine, reads
   `data/tune-reference.txt` (3,357 tokens of the model's own reasoning) through the decode windows, and records the
   speed and every token's log-probability.
2. **A second look when it is close.** The fastest setting within the quality budget wins, unless a better-quality one
   is within 3%. When the two fastest are 1.5-4.5% apart (the 3% rule could go either way), both are read again.
3. **The PCIe share** (NVIDIA): the profile's 0.75, 0.55 and the engine's own probe, on one engine (the share is set
   per request), two rounds in alternating order after two warm-up reads. A change is kept only if it is faster in
   every round and by more than 3% at the median, as in Strata's calibrate.

The launcher's guards stay on throughout. The report goes to `.gyro-recipe\tune\last-run.txt`.

**Free RAM matters.** The launcher sizes the RAM expert tier from the RAM free at start-up, and the file skip only drops
experts that are not in it, so its quality cost depends on that size: file 2 + tail 7 cost +0.028 with 13 GiB of
experts in RAM and +0.018 to +0.020 with 14 GiB, while file 3 + tail 6 stayed at +0.014 to +0.016. The tuning file
records the tier it was measured with, and the launcher applies it only when at least that much is in RAM; otherwise
it says so and uses the profile's defaults. Tune with your usual apps open, not right after a reboot.

**How exact is the quality number?** Repeated runs on the same PC and RAM tier give the same values to 0.002 or better.
The reference text is one sample of reasoning, though: on other text the cost can differ by about 0.006 (its standard
error), and it grows with the length of the text, because skipped experts change the state later tokens build on.

Runs on my PC (all chose file 3 + tail 6 under the balanced budget):

| Run | Experts in RAM | Settings read | Minutes | file 3 + tail 6 dNLL | PCIe share kept |
|---|---:|---:|---:|---:|---|
| first tuner, 9 settings x up to 3 | 13 GiB | 24 | 31 (with `--confirm`) | +0.0145 | 0.75 (others +1.9-2.4%) |
| first tuner, fresh install | 14 GiB | 24 | 25.5 | +0.0161 | engine probe (+3.9-5.4%) |
| first tuner, repeated | 14 GiB | 24 | 27 | +0.0138 | engine probe (+3.8-4.3%) |
| **current tuner** | 14 GiB | 8 + 1 PCIe engine | **11.3** (7.3 + 2.1 + 2) | +0.0138 | 0.55 (+3.5-4.8%) |

Report of the current tuner on my PC:

```text
  experts on the SSD: yes (file-skip settings)
  off            33.9 tok/s  dNLL +0.0000  top-1 1.000  KL 0.0000
  file3          65.1 tok/s  dNLL +0.0088  top-1 0.918  KL 0.0312
  file3+tail7    72.7 tok/s  dNLL +0.0090  top-1 0.915  KL 0.0382
  file3+tail6    75.7 tok/s  dNLL +0.0138  top-1 0.903  KL 0.0444
  file2+tail7    76.8 tok/s  dNLL +0.0203  top-1 0.900  KL 0.0488  (over the quality budget)
  file2+tail6    81.4 tok/s  dNLL +0.0242  top-1 0.894  KL 0.0547  (over the quality budget)
Step 2: the leaders again (file3+tail6, file3+tail7; 4.1% apart, close to the 3% rule)
  again: file3+tail6 76.0, file3+tail7 72.8
Chosen: file3+tail6 (median 75.8 tok/s through the windows, dNLL +0.0138)
  round 1: 0.75 83.0, auto 85.5, 0.55 85.9
  round 2: 0.75 86.7, auto 89.1, 0.55 90.9
  PCIe share: 0.55
```

Window-read speeds are not reply speeds (several tokens are read per step); they rank settings the way real replies
did. The first tuner's `--confirm` reply measured 20.2 tok/s with skipping off and 31.4 with file 3 + tail 6
(a short-context reply; the 32K replies below are the reference numbers).
## What decides the speed on 12 GB VRAM / 32 GB RAM

Gyro-M's experts do not fit in VRAM + RAM. During a real reasoning reply, each token's 48 MoE layers find most of
their experts in VRAM, some in RAM (computed by the CPU), and a few only on the SSD. Measured on my PC at
32K context, one decode step took about 68.5 ms:

| Part of a decode step | Time |
|---|---:|
| GPU (attention, VRAM experts) | 13.5 ms |
| CPU math for RAM experts | 10.6 ms |
| **Waiting for expert reads from the SSD** | **38.5 ms** |

So the lever is not the CPU or GPU settings: it is not waiting for the SSD.

## The recipe

Strata can skip a missed expert that the router ranked low (its weight is small); the reply changes slightly.

- **STRATA_ROUTE_TAIL_SKIP=R** (Strata): skips an expert missing from VRAM when every token in the decode step ranks it
  R-th or later among its 10 experts (rank 0 has the largest weight, rank 9 the smallest). Strata turns it on (R=7) by default on such cards; GyroStrata used to switch it off.
- **STRATA_FILE_SKIP=R** (GyroStrata patch): the same, but only for experts that are in neither VRAM nor RAM - the
  ones the layer would wait on the SSD for. RAM experts are still computed, so it costs less quality per tok/s.

Shipped default: **STRATA_FILE_SKIP=3 + STRATA_ROUTE_TAIL_SKIP=6** ("balanced"). Other profile changes: conversation
cache 3 GiB on 32 GB RAM (4 GiB let a 128K follow-up hit the 512 MiB RAM floor), VRAM reserve 1216 MiB (1024 put a
12 GB card with a busy desktop over the guard on its first request).

## Measured data (my PC, 2026-10-19)

One desktop with a 12 GB NVIDIA GPU (PCIe 4.0 x16), 32 GB RAM and a PCIe 4.0 NVMe SSD, Windows 11.

**Quality** - 3,357 tokens of the model's own reasoning, teacher-forced through the decode windows (STRATA_LOGPOS).
dNLL is the mean increase in negative log-likelihood against no skipping (0.01 = about 1% perplexity); top-1 is how
often the most likely next token is unchanged. Two runs of the same setting are bit-identical.

| Setting | Window read | dNLL | Top-1 | KL (top-20 est.) |
|---|---:|---:|---:|---:|
| off | 125 s | 0 | 1.000 | 0 |
| tail 7 (Strata default) | 95 s | +0.0004 | 0.924 | 0.024 |
| tail 5 | 74 s | +0.014 | 0.901 | 0.043 |
| tail 4 | 64 s | +0.023 | 0.883 | 0.060 |
| tail 3 | 51 s | +0.061 | 0.858 | 0.092 |
| file 3 | 56 s | +0.0105 | 0.907 | 0.034 |
| file 2 | 51 s | +0.017 | 0.903 | 0.045 |
| **file 3 + tail 6 (default)** | **46 s** | **+0.016** | **0.895** | **0.048** |
| file 2 + tail 7 | 45 s | +0.028 | 0.890 | 0.055 |
| file 2 + tail 5 | 40 s | +0.039 | 0.878 | 0.069 |

**Speed on real work** - the engine's own C++ sources as context plus a code-review question, thinking on,
the profile's sampling, 6,144-token replies; then a follow-up turn on the same conversation.

| Setting | 32K cold | 32K follow-up | 128K cold | 128K follow-up |
|---|---:|---:|---:|---:|
| off (old profile) | 15.9-16.7 | 15.2-16.0 | 15.8 | stopped: RAM floor |
| tail 7 | 25.8 | 25.2 | | |
| tail 5 | 30.4 | 29.2 | | |
| tail 4 | 33.6 | 32.6 | | |
| file 3 | 32.5 | 32.3 | | |
| file 2 | 34.0 | 32.5 | | |
| file 2 + tail 7 | 36.8 | 35.5 | | |
| **file 3 + tail 6** (2 runs) | **33.3-37.0** | **32.8-34.8** | **31.8-34.1** | **30.3-32.2** |

Rejected, measured: a direct-I/O read-ahead of the router look-ahead's predicted experts (only a third of the reads
were used; no gain once the file skip was on), P-core-only CPU affinity (-5% in a short test), MTP drafting (slower in the maintainer's own
measurements; the GGUF also has no MTP tensors).

## Lessons for measuring

- **Short benchmarks mislead.** A 256-token code continuation lets suffix speculation accept 2.3-2.7 tokens per decode
  step; natural reasoning gets 1.1. The old grid (29.7-38.4 tok/s) was about twice the real reasoning speed (16).
- **Sampled runs vary by about 10%** (different text routes different experts). Compare large effects only, or use
  the teacher-forced read, which is deterministic.
- **Measure quality, do not assume it.** STRATA_LOGPOS through `--short-read 4096` gives exact per-token
  log-probabilities for any setting in about two minutes.
- **Check memory over two turns at long context**, not one: the conversation cache grows after the first reply.
