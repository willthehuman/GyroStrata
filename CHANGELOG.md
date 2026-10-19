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
