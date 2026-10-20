# 1.2.0

- About twice the output speed on real reasoning (on my 12 GB / 32 GB PC: 16 -> 33-37 tok/s at 32K, 16 -> 30-34 at 128K): the profile now skips low-ranked missed experts (STRATA_ROUTE_TAIL_SKIP=6, which the old profile had switched off) and low-ranked SSD-only experts (new STRATA_FILE_SKIP=3). Quality cost measured: mean NLL +0.016.
- Added START-HERE.cmd: one double-click downloads the model (with progress) while the engine builds, then installs, tunes and offers to start the model. Finished steps are skipped when it is run again.
- INSTALL.cmd skips the engine build when the existing one already matches the GPU, the source and patch pins and the selected CUDA toolkit (its tests ran when it was built); any change rebuilds it.
- Added TUNE.cmd (about 11 minutes on my PC): measures expert skipping and the PCIe share on your PC under a quality budget (exact, balanced, fast); it reads only the settings that can win on that PC and compares PCIe shares on one engine and saves the result beside the weights; the launcher applies it while the hardware, the engine patch and the free RAM still match what it measured.
- Added TUNING.md: the recipe, the speed and quality data and the measuring method; it replaces the README's AI tuning prompt.
- Fixed a first-request crash on 12 GB cards with a busy desktop: the default VRAM reserve is 1216 MiB.
- Fixed long two-turn conversations on 32 GB RAM stopping at the 512 MiB RAM floor: the conversation cache is 3 GiB below 48 GB RAM.
- build.cmd also builds and runs pool_tasks_test, a patched CPU-pool test that no install ran before.
- Fixed a race in the engine: a RAM rebalance could rewrite an expert while the Foresight swap space copied from it (regression test added).

# 1.1.0

- Fixed corrupted model weights on RTX 50-series GPUs that stopped installation; these GPUs now need CUDA 13.2 Update 2.
- Fixed the model downloader's 404 error.
- Updated the engine to Strata v0.1.45.
- Added an experimental Windows AMD/HIP build, with device selection, VRAM monitoring and parity checks.
- Made the context benchmark's marker check reliable and documented VRAM reserve tuning.
- Updated Windows CI.

# 1.0.0

- Imported native Gyro trellis/Hadamard support into pinned Strata, with CPU/GPU parity checks.
- Added CPU row-construction optimization, SSD/CPU overlap, RAM expert rebalancing, configurable read merging, conversation-tail retention and suffix-cost reprobes.
- Selected a 256K text profile with Q4 KV, 32K GPU pages, adaptive prefill and resource-aware expert budgets.
- Added resumable model download, GPU-specific Windows builds, existing-model reuse, one launcher and keyless API by default.
- Added source/model/pack verification, runtime memory guards, profile locks, rollback and owned-process cleanup.
- Tested installer failures and path handling; added Windows CI, the three-run speed grid and a hardware-specific AI tuning prompt.

See [README.md](README.md#changelog) for the short feature list and [PATCHES.md](PATCHES.md) for attribution and source changes. This is a tuned Strata baseline, not a rewrite or a universal speed guarantee.
