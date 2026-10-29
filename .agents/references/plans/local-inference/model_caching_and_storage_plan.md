# Model Storage, Caching, and Capacity Validation Plan

**Document Version:** 1.1.0  
**Date:** 2026-10-20  
**Target Hardware:** Dual-Blackwell Workstation (NVMe Mount `/dev/nvme0n1p2`, 3.6 TB Storage + Secondary NVMe `/dev/nvme1n1p1`, 3.6 TB Storage)  
**Parent Plan:** [`experiment_03.md`](./experiments/experiment_03.md)  
**Campaign Ledger:** [`experiments.md`](./experiments/experiments.md)  

---

## 1. Executive Storage Audit & Dual-Drive Partitioning

A physical storage audit was performed across both host NVMe drives:

```text
Drive / Partition          Label / Purpose       Mount Path      Total   Used    Available   Use%
/dev/nvme0n1p2 (Primary)   OS, Sim & Active Exp  / & /workspaces 3.6 TB  3.3 TB  175 GB      95% (Expanding to ~653 GB)
/dev/nvme1n1p1 (Secondary) colibri_models        /mnt/nvme1      3.6 TB  663 GB  2.9 TB      18% (Abundant archive space)
```

### Key Migration Findings & Actions
* **Initial State:** Primary NVMe was critically full at **98% (88 GB available)**.
* **Datasets Migration:** `/datasets/isaaclab_arena` (**40 GB** comprising `locomanipulation_tutorial` 23 GB and `static_apple_tutorial` 17 GB) was verified and migrated to `/mnt/nvme1/archive/datasets/` and replaced with symbolic links, freeing **40 GB**.
* **Inactive Models Migration:** `/models/isaaclab_arena/locomanipulation_tutorial` (**48 GB**) was migrated to `/mnt/nvme1/archive/models/` and replaced with a symlink, freeing **48 GB**.
* **Massive Archive Migration:** `/models/isaaclab_arena/static_apple_tutorial` (**477 GB** of older experiment runs and geometry sweeps) is migrated to `/mnt/nvme1/archive/models/`, which reclaims **477 GB**.
* **Projected Final Primary Free Space:** **~653 GB** available on `/dev/nvme0n1p2` (dropping use to ~82%).
* **Preservation Policy:** All active models and assets required for Experiment 03 remain 100% on high-speed primary NVMe storage.

---

## 2. Model Inventory, Cache Locations & Status

| Model Subsystem | Checkpoint Identifier | Cache Directory on Host | Disk Size | Local Status | Serving Mechanism |
| :--- | :--- | :--- | :---: | :---: | :--- |
| **Policy Model (Candidate A)** | `nvidia/GR00T-N1.6-DROID` | `/root/.cache/huggingface/hub/models--nvidia--GR00T-N1.6-DROID` | **6.2 GB** | **VERIFIED (Primary NVMe)** | `gr00t-server` (ZeroMQ port 5556) |
| **Policy Model (Candidate A)** | `nvidia/GR00T-N1.7-3B` | `/root/.cache/huggingface/hub/models--nvidia--GR00T-N1.7-3B` | **11.0 GB** | **VERIFIED (Primary NVMe)** | `gr00t-server` (ZeroMQ port 5556) |
| **Cognitive Spec LLM** | `Qwen/QwQ-32B-AWQ` | `/root/.cache/huggingface/hub/models--Qwen--QwQ-32B-AWQ` | **19.0 GB** | **VERIFIED (Primary NVMe)** | `vllm-openai` (HTTP port 8001) |
| **Cognitive Spec LLM** | `zai-org/GLM-5.3-Flash` | `/models/glm-5.3` (Mirror Symlink) | Mounted | **VERIFIED (Mounted)** | `vllm-openai` (HTTP port 8001) |
| **Policy Model (Candidate D)** | `pi05_droid_jointpos` | `/root/.cache/openpi/openpi-assets-simeval/pi05_droid_jointpos` | **11.58 GB** | **VERIFIED (Primary NVMe)** | `openpi-server` (WebSocket port 8000) |
| **Kinematic USD Assets** | `Microwave039.usd` + Props | `/root/.cache/lightwheel_sdk/object/` | **~1.2 GB** | **VERIFIED (Container Cache)** | Native Isaac Sim USD Stage |
| **Archived Datasets** | `static_apple` + `locomanip` | `/mnt/nvme1/archive/datasets/` | **40.0 GB** | **MIGRATED & SYMLINKED** | Secondary NVMe (`colibri_models`) |
| **Archived Models** | `static_apple` + `locomanip` | `/mnt/nvme1/archive/models/` | **525.0 GB** | **MIGRATED & SYMLINKED** | Secondary NVMe (`colibri_models`) |

---

## 3. OpenPI Ingestion & Headroom Budget Plan

OpenPI ($\pi_0$ / $\pi_{0.5}$) requires a one-time container build and weights ingestion from Google Cloud Storage (`gs://openpi-assets-simeval/`):

```
Current NVMe Free Space:             89.0 GB
- OpenPI Server Image Build:         12.0 GB
- OpenPI pi05 Checkpoint Download:   11.0 GB
- Temporary Layer Overhead:           3.0 GB
─────────────────────────────────────────────
Projected Net Free Space:            63.0 GB (> 3x the 20 GB safety threshold)
```

### Execution Command with Explicit Cache Mount

```bash
# Set explicit cache directory to host path
export OPENPI_CACHE_DIR="/root/.cache/openpi"
mkdir -p "$OPENPI_CACHE_DIR"

# Build image and cache ~11GB pi05 weights across runs
./isaaclab_arena_openpi/docker/run_openpi_server.sh -v pi05
```

---

## 4. Pre-Launch Validation Checklist & Shell Commands

Run these verification commands before initiating long-running evaluation rollouts:

### Check 1: Verify Free Disk Space
```bash
python3 -c "
import shutil
total, used, free = shutil.disk_usage('/')
free_gb = free // (2**30)
print(f'NVMe Free Space: {free_gb} GB')
assert free_gb >= 25, f'Insufficient disk space! Only {free_gb} GB free.'
print('✓ Disk headroom check passed.')
"
```

### Check 2: Verify Existing Model Checkpoints
```bash
python3 -c "
import os
checkpoints = [
    '/root/.cache/huggingface/hub/models--nvidia--GR00T-N1.6-DROID',
    '/root/.cache/huggingface/hub/models--nvidia--GR00T-N1.7-3B',
    '/root/.cache/huggingface/hub/models--Qwen--QwQ-32B-AWQ',
    '/root/.cache/lightwheel_sdk/object/Microwave039/Microwave039.usd'
]
for p in checkpoints:
    exists = os.path.exists(p)
    print(f'[{ \"✓ OK\" if exists else \"✗ MISSING\" }] {p}')
"
```

### Check 3: Emergency Space Recovery (If Free Space < 20 GB)
If unexpected Docker build cache accumulation pushes free space below 20 GB, execute non-destructive build cache pruning:
```bash
# Reclaims up to 254 GB of stale BuildKit cache without affecting existing images or model weights
docker builder prune -f
docker system prune -f --volumes=false
```

---

## 5. Rollout Artifact & Video Retention Policy

To prevent the 89 GB headroom from degrading during multi-seed evaluation batches:
1. **Snapshots Only for Ledger**: Video extraction generates 3 lightweight PNG snapshots per episode (`t0`, `mid`, `tfinal`) amounting to $< 1.5\text{ MB}$ per rollout.
2. **Video Compression**: Output MP4s are captured at 50 Hz H.264 CRF 23, consuming $\approx 8\text{ MB}$ per 1,000-step episode.
3. **Budget Cap**: 30 rollouts across Sub-Tasks 3A, 3B, and 3C consume $< 300\text{ MB}$ of total artifact storage, completely preserving NVMe capacity.
