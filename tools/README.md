# Tools

Utility scripts for debugging and inspecting models and robot configurations used in IsaacLab Arena.

## analyze_model_tensors.py

**Purpose:** Inspects `.safetensors` model checkpoint files to understand their internal tensor structure — shapes, dtypes, and how they're organized into architectural components.

### Usage

```bash
# Use the default filename (model-00002-of-00002.safetensors) — auto-discovered from /models
python tools/analyze_model_tensors.py
```

#### Examples

```bash
# 1. GR00T N1.6 G1 Pick-and-Place Apple to Plate
python tools/analyze_model_tensors.py \
  models/isaaclab_arena/GR00T-N1.6-G1-PnPAppleToPlate/checkpoint-20000/model-00002-of-00002.safetensors

# 2. Locomanipulation Tutorial
python tools/analyze_model_tensors.py \
  models/isaaclab_arena/locomanipulation_tutorial/checkpoint-20000/model-00002-of-00002.safetensors

# 3. Sequential Static Manipulation Tutorial (Ranch Bottle into Fridge)
python tools/analyze_model_tensors.py \
  models/isaaclab_arena/sequential_static_manipulation_tutorial/_hf_download/ranch_bottle_into_fridge/model-00002-of-00002.safetensors

# 4. Static Manipulation Tutorial
python tools/analyze_model_tensors.py \
  models/isaaclab_arena/static_manipulation_tutorial/checkpoint-20000/model-00002-of-00002.safetensors
```

> **Note:** Each model checkpoint is split into two shards (`model-00001-of-00002.safetensors` and `model-00002-of-00002.safetensors`). You can analyze either shard independently.

### How It Works

1. **Reads the safetensors header** — parses the binary header (8-byte length prefix → JSON metadata) without loading the full tensor data into memory.
2. **Groups and prints tensors by architectural role:**
   - **State Encoder** — tensors with `state_encoder` in their key (proprioception inputs)
   - **Action Decoder** — tensors with `action_decoder` in their key (motor outputs)
   - **Transformer / Attention blocks** — tensors with `attention` or `self_attn` in their key (shows first 10)
   - **Output Head / Projection** — tensors with `head`, `projection`, or `output` in their key
3. **Auto-discovery:** If the specified file isn't found, it searches the current working directory, `/workspaces/IsaacLab-Arena/models/`, and the repo root for matching filenames. If none match, it lists all `.safetensors` files it can find and defaults to the first one.

### What You Learn from the Output

- Total tensor count in the checkpoint.
- The **input dimension** of the state encoder (tells you how many proprioception features the model expects).
- The **output dimension** of the action decoder (tells you how many joint actions the model produces).
- The model's transformer architecture depth and width.

---

## inspect_link_positions.py

**Purpose:** Spawns the `g1_brainco_custom` robot in a headless Isaac Sim session and prints the world-space positions of every body link. It then specifically checks that the head link is correctly positioned relative to the torso.

### Usage

This script requires Isaac Sim and must be run inside the Docker container:

```bash
docker exec isaaclab_arena-latest bash -c "cd /workspaces/isaaclab_arena && \
  /isaac-sim/python.sh tools/inspect_link_positions.py"
```

### How It Works

1. **Initializes Isaac Sim** via `AppLauncher` in headless mode.
2. **Loads the `g1_brainco_custom` embodiment** from the `AssetRegistry` and creates an `InteractiveScene` with a ground plane.
3. **Steps the simulation 10 times** to let the articulation settle.
4. **Prints all link positions** — iterates through `robot.data.body_names` and prints each link's world-space `(x, y, z)` position.
5. **Head-vs-torso validation** — computes the displacement between `torso_link` and `head_link` and checks that the head is at least 0.1m above the torso. If not, it prints a **WARNING** about a possible collapsed or mispositioned head joint.

### What You Learn from the Output

- The world-space coordinates of every body link on the robot (useful for debugging URDF/USD misconfigurations).
- Whether the `head_link` is properly positioned above the `torso_link` (a sanity check for the G1 BrainCo embodiment's kinematic chain).

---

## Quick Reference

| Tool | Requires Sim? | Input | Key Output |
|---|---|---|---|
| `analyze_model_tensors.py` | No | `.safetensors` file path | Tensor names, shapes, dtypes grouped by architectural role |
| `inspect_link_positions.py` | Yes (Isaac Sim) | None (hardcoded to `g1_brainco_custom`) | World-space link positions + head/torso height sanity check |
