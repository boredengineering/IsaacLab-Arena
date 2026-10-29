# SimReady Central MCP Server Instructions

## Purpose
The `simready-central` MCP server provides real-time access to NVIDIA SimReady Central's live DeepSearch engine (`https://nvidia-simready-central.hf.space`) and verified OEM submission repositories (`https://github.com/NVIDIA-Omniverse/simready-central`).

Use this tool to find, inspect, download, and ground production OpenUSD assets (fixtures, articulators, manipulators, grippers, and manipulands) into IsaacLab-Arena.

## Available Tools
1. `simready_search`:
   - Natural language and keyword search across 2,500+ production simulation-ready assets.
   - Combines BM25 text match with SigLIP2 1536-dimensional multimodal embeddings.
2. `simready_get_manifest`:
   - Inspects `com.nvidia.simready.packaging.json` for license (e.g. CC-BY-4.0), package hash, and BOM components.
3. `simready_download`:
   - Downloads `.usd` / `.usdc` stages and payloads into `artifacts/assets/simready/`.
4. `simready_list_oem_submissions`:
   - Queries verified submissions from leading robotics OEMs: `nvidia`, `frankarobotics`, `Robotiq-Official`, `FANUC-CORPORATION`, `Comau`, etc.

## Epistemic Resolution Pattern
When an asset query returns $\text{Unknown}$ in the Orchestrator (e.g., missing fixture):
1. Call `simready_search(query="office desk drawer")`.
2. Inspect candidate hits and confirm domain alignment ($\text{Sim} \ge 0.70$).
3. Call `simready_download(asset_url=hit.download_url)`.
4. Run `introspect_usd_fixture` on the local file to verify ground contact ($Z_{\min} = 0.0\text{ m}$) and deck height.
5. Register into `AssetRegistry` and transition proposition $\text{Unknown} \to \text{True}$.
