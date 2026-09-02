# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unified Environment and Evaluation Versioning & Lineage Manager.

Provides structured, clean version tracking across `generated_envs/<env_name>/`
and `eval_output/<env_name>/` to replace ad-hoc folder sprawl with deterministic
lineage tracking (JSON and W3C PROV-O RDF-star).
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from rdflib import Graph, Literal, Namespace, RDF, URIRef
from rdflib.namespace import PROV, XSD

ARENA = Namespace("https://isaac-sim.github.io/arena/schema#")
INSTANCE = Namespace("https://isaac-sim.github.io/arena/instances/")


class EnvironmentVersionManager:
    """Manages versioned environment generation and evaluation lifecycles.

    Layout:
        generated_envs/<env_name>/
            lineage.json
            lineage.ttl
            latest -> vN/
            v1/
                <env_name>.yaml
                policy_config.yaml
                metadata.json
            v2/
                ...

        eval_output/<env_name>/
            v1/
                episode_results_rank0.jsonl
                eval_telemetry.ttl
                summary_metrics.json
                index.html
            v2/
                ...
    """

    def __init__(
        self,
        env_name: str,
        generated_envs_root: Path | str = Path("/workspaces/isaaclab_arena/generated_envs"),
        eval_output_root: Path | str = Path("/workspaces/isaaclab_arena/eval_output"),
    ) -> None:
        self.env_name = env_name.strip()
        self.gen_root = Path(generated_envs_root).resolve()
        self.eval_root = Path(eval_output_root).resolve()

        self.env_dir = self.gen_root / self.env_name
        self.env_eval_dir = self.eval_root / self.env_name

        self.lineage_file = self.env_dir / "lineage.json"
        self.lineage_ttl_file = self.env_dir / "lineage.ttl"

    def get_latest_version(self) -> int:
        """Return the latest integer version number, or 0 if no versions exist."""
        if not self.lineage_file.exists():
            if not self.env_dir.exists():
                return 0
            existing_v = []
            for child in self.env_dir.iterdir():
                if child.is_dir() and child.name.startswith("v") and child.name[1:].isdigit():
                    existing_v.append(int(child.name[1:]))
            return max(existing_v) if existing_v else 0

        try:
            with open(self.lineage_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return int(data.get("current_version", 0))
        except Exception:
            return 0

    def get_version_dir(self, version: int | None = None) -> Path:
        """Return the directory for a given version (or latest if None)."""
        v = version if version is not None else self.get_latest_version()
        if v <= 0:
            v = 1
        return self.env_dir / f"v{v}"

    def get_eval_dir(self, version: int | None = None) -> Path:
        """Return the evaluation directory for a given version (or latest if None)."""
        v = version if version is not None else self.get_latest_version()
        if v <= 0:
            v = 1
        return self.env_eval_dir / f"v{v}"

    def get_spec_yaml_path(self, version: int | None = None) -> Path:
        """Return the primary specification YAML path for a version."""
        v_dir = self.get_version_dir(version)
        yaml_candidates = list(v_dir.glob("*.yaml"))
        for candidate in yaml_candidates:
            if candidate.name.endswith("_env_graph.yaml") or candidate.stem == self.env_name:
                return candidate
        if yaml_candidates:
            return yaml_candidates[0]
        return v_dir / f"{self.env_name}.yaml"

    def get_policy_config_path(self, version: int | None = None) -> Path | None:
        """Return the policy config YAML path for a version if present."""
        v_dir = self.get_version_dir(version)
        for name in ("policy_config.yaml", "droid_manip_gr00t_closedloop_config.yaml", "policy.yaml"):
            candidate = v_dir / name
            if candidate.exists():
                return candidate
        yaml_candidates = [f for f in v_dir.glob("*.yaml") if f != self.get_spec_yaml_path(version)]
        return yaml_candidates[0] if yaml_candidates else None

    def create_version(
        self,
        spec_source: Path | dict[str, Any] | str,
        policy_config_source: Path | dict[str, Any] | str | None = None,
        trigger: str = "generation",
        prompt: str | None = None,
        parent_version: int | None = None,
        remediations: list[str] | None = None,
        diagnostics: list[str] | None = None,
    ) -> tuple[int, Path]:
        """Create a new version snapshot in generated_envs/<env_name>/v{N+1}/.

        Args:
            spec_source: Path to YAML file or raw dictionary/string.
            policy_config_source: Optional policy configuration YAML/path/dict.
            trigger: Cause of version creation (e.g. 'initial_prompt', 'auto_heal', 'user_refine').
            prompt: Original or refined text prompt.
            parent_version: Preceding version number.
            remediations: List of repair actions applied.
            diagnostics: Identified defects/signatures that led to this version.

        Returns:
            Tuple of (new_version_number, new_version_dir_path).
        """
        current_v = self.get_latest_version()
        new_v = current_v + 1
        new_v_dir = self.env_dir / f"v{new_v}"
        new_v_dir.mkdir(parents=True, exist_ok=True)
        target_spec_file = new_v_dir / f"{self.env_name}.yaml"
        if hasattr(spec_source, "write_yaml"):
            spec_source.write_yaml(target_spec_file)
        elif hasattr(spec_source, "model_dump"):
            import yaml

            with open(target_spec_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(spec_source.model_dump(mode="json", exclude_none=True), f, sort_keys=False)
        elif isinstance(spec_source, (str, Path)) and Path(spec_source).exists():
            shutil.copy(Path(spec_source), target_spec_file)
        elif isinstance(spec_source, dict):
            import yaml

            with open(target_spec_file, "w", encoding="utf-8") as f:
                yaml.safe_dump(spec_source, f, sort_keys=False)
        elif isinstance(spec_source, str):
            with open(target_spec_file, "w", encoding="utf-8") as f:
                f.write(spec_source)

        target_policy_file = None
        if policy_config_source:
            target_policy_file = new_v_dir / "policy_config.yaml"
            if isinstance(policy_config_source, (str, Path)) and Path(policy_config_source).exists():
                shutil.copy(Path(policy_config_source), target_policy_file)
            elif isinstance(policy_config_source, dict):
                import yaml

                with open(target_policy_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(policy_config_source, f, sort_keys=False)
            elif isinstance(policy_config_source, str):
                with open(target_policy_file, "w", encoding="utf-8") as f:
                    f.write(policy_config_source)
        else:
            # Auto-scaffold canonical policy config based on embodiment
            emb_name = ""
            if hasattr(spec_source, "embodiment") and spec_source.embodiment:
                emb_name = getattr(spec_source.embodiment, "registry_name", "") or ""
            elif isinstance(spec_source, dict):
                emb_name = spec_source.get("embodiment", {}).get("registry_name", "")

            import yaml
            target_policy_file = new_v_dir / "policy_config.yaml"
            if "g1" in emb_name.lower():
                default_cfg = {
                    "language_instruction": prompt or "move the apple to the plate",
                    "action_horizon": 40,
                    "action_chunk_length": 20,
                    "embodiment_tag": "NEW_EMBODIMENT",
                    "video_backend": "decord",
                    "modality_config_path": "isaaclab_arena_gr00t/embodiments/g1/g1_sim_wbc_data_gr00t_n_1_7_config.py",
                    "policy_joints_config_path": "isaaclab_arena_gr00t/embodiments/g1/gr00t_43dof_joint_space.yaml",
                    "action_joints_config_path": "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
                    "state_joints_config_path": "isaaclab_arena_gr00t/embodiments/g1/43dof_joint_space.yaml",
                    "pov_cam_name_sim": "robot_head_cam_rgb",
                    "task_mode_name": "g1_locomanipulation",
                }
                with open(target_policy_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default_cfg, f, sort_keys=False)
            else:
                default_cfg = {
                    "language_instruction": prompt or "pick up the object and place it into the container",
                    "action_horizon": 32,
                    "action_chunk_length": 16,
                    "embodiment_tag": "OXE_DROID",
                    "video_backend": "decord",
                    "modality_config_path": "isaaclab_arena_gr00t/embodiments/droid/droid_sim_data_config.py",
                    "pov_cam_name_sim": "external_camera_rgb",
                    "wrist_cam_name_sim": "wrist_camera_rgb",
                }
                with open(target_policy_file, "w", encoding="utf-8") as f:
                    yaml.safe_dump(default_cfg, f, sort_keys=False)

        # Update symlink / latest pointer
        latest_dir = self.env_dir / "latest"
        if latest_dir.is_symlink() or latest_dir.exists():
            if latest_dir.is_symlink():
                latest_dir.unlink()
            elif latest_dir.is_dir():
                shutil.rmtree(latest_dir)
        try:
            latest_dir.symlink_to(f"v{new_v}")
        except Exception:
            pass

        # Update lineage ledger
        self._update_lineage_ledger(
            version=new_v,
            trigger=trigger,
            prompt=prompt,
            parent_version=parent_version or (current_v if current_v > 0 else None),
            remediations=remediations or [],
            diagnostics=diagnostics or [],
            spec_file=str(target_spec_file.relative_to(self.gen_root)),
            policy_file=str(target_policy_file.relative_to(self.gen_root)) if target_policy_file else None,
        )

        self.generate_readme()

        return new_v, new_v_dir

    def record_evaluation_metrics(
        self,
        version: int,
        metrics: dict[str, Any],
        eval_output_dir: Path | str | None = None,
    ) -> None:
        """Record evaluation outcome for a specific version in the lineage ledger."""
        if not self.lineage_file.exists():
            return

        with open(self.lineage_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for entry in data.get("versions", []):
            if entry.get("version") == version:
                eval_entry = {
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "eval_dir": str(eval_output_dir or self.get_eval_dir(version)),
                    "success_rate": metrics.get("success_rate", 0.0),
                    "object_moved_rate": metrics.get("object_moved_rate", 0.0),
                    "num_episodes": metrics.get("num_episodes", 0),
                    "progress_score": metrics.get("progress_score", 0.0),
                    "raw_metrics": metrics,
                }
                entry["evaluation"] = eval_entry
                break

        with open(self.lineage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._sync_prov_rdf(data)
        self.generate_readme()

    def _update_lineage_ledger(
        self,
        version: int,
        trigger: str,
        prompt: str | None,
        parent_version: int | None,
        remediations: list[str],
        diagnostics: list[str],
        spec_file: str,
        policy_file: str | None,
    ) -> None:
        """Update lineage.json and sync W3C PROV-O RDF-star graph."""
        now = datetime.now(timezone.utc).isoformat()
        if self.lineage_file.exists():
            try:
                with open(self.lineage_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
            except Exception:
                data = {"env_name": self.env_name, "created_at": now, "versions": []}
        else:
            data = {"env_name": self.env_name, "created_at": now, "versions": []}

        data["current_version"] = version
        data["updated_at"] = now

        version_entry = {
            "version": version,
            "created_at": now,
            "trigger": trigger,
            "prompt": prompt,
            "parent_version": parent_version,
            "remediations": remediations,
            "diagnostics": diagnostics,
            "spec_file": spec_file,
            "policy_file": policy_file,
            "evaluation": None,
        }

        data["versions"] = [v for v in data.get("versions", []) if v.get("version") != version]
        data["versions"].append(version_entry)
        data["versions"].sort(key=lambda x: x["version"])

        with open(self.lineage_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

        self._sync_prov_rdf(data)

    def _sync_prov_rdf(self, data: dict[str, Any]) -> None:
        """Serialize version lineage to W3C PROV-O Turtle format."""
        g = Graph()
        g.bind("arena", ARENA)
        g.bind("prov", PROV)
        g.bind("", INSTANCE)

        env_entity = INSTANCE[self.env_name]
        g.add((env_entity, RDF.type, ARENA.EnvironmentFamily))
        g.add((env_entity, ARENA.currentVersion, Literal(data.get("current_version", 1), datatype=XSD.integer)))

        for entry in data.get("versions", []):
            v_num = entry["version"]
            v_uri = INSTANCE[f"{self.env_name}_v{v_num}"]
            g.add((v_uri, RDF.type, ARENA.EnvironmentVersion))
            g.add((v_uri, RDF.type, PROV.Entity))
            g.add((v_uri, ARENA.versionNumber, Literal(v_num, datatype=XSD.integer)))
            g.add((v_uri, ARENA.trigger, Literal(entry.get("trigger", "generation"), datatype=XSD.string)))
            g.add((v_uri, PROV.generatedAtTime, Literal(entry.get("created_at", ""), datatype=XSD.dateTime)))

            parent_v = entry.get("parent_version")
            if parent_v:
                parent_uri = INSTANCE[f"{self.env_name}_v{parent_v}"]
                g.add((v_uri, PROV.wasDerivedFrom, parent_uri))

            for rem in entry.get("remediations", []):
                g.add((v_uri, ARENA.remediationAction, Literal(rem, datatype=XSD.string)))

            for diag in entry.get("diagnostics", []):
                g.add((v_uri, ARENA.failureDiagnostic, Literal(diag, datatype=XSD.string)))

            eval_data = entry.get("evaluation")
            if eval_data:
                g.add((v_uri, ARENA.successRate, Literal(eval_data.get("success_rate", 0.0), datatype=XSD.float)))
                g.add((v_uri, ARENA.evalDir, Literal(eval_data.get("eval_dir", ""), datatype=XSD.string)))

        try:
            g.serialize(destination=str(self.lineage_ttl_file), format="turtle")
        except Exception:
            pass

    def generate_readme(self) -> Path:
        """Generate and save an actionable, developer-friendly README.md for this environment.

        Returns:
            Path to the written README.md file.
        """
        current_v = self.get_latest_version()
        if current_v <= 0:
            current_v = 1

        lineage_data: dict[str, Any] = {}
        if self.lineage_file.exists():
            try:
                with open(self.lineage_file, "r", encoding="utf-8") as f:
                    lineage_data = json.load(f)
            except Exception:
                pass

        versions = lineage_data.get("versions", [])
        latest_entry = next((v for v in reversed(versions) if v.get("version") == current_v), versions[-1] if versions else {})
        prompt = (
            latest_entry.get("prompt")
            or (versions[0].get("prompt") if versions else None)
            or f"Active Inference environment task definition for {self.env_name}."
        )

        spec_yaml_name = self.get_spec_yaml_path(current_v).name
        spec_abs_path = f"/workspaces/isaaclab_arena/generated_envs/{self.env_name}/latest/{spec_yaml_name}"
        policy_config_abs_path = f"/workspaces/isaaclab_arena/generated_envs/{self.env_name}/latest/policy_config.yaml"
        eval_output_abs_path = f"/workspaces/isaaclab_arena/eval_output/{self.env_name}"

        # Build lineage table rows
        table_rows = []
        if versions:
            for v_info in versions:
                v_num = f"`v{v_info.get('version', 1)}`"
                created = (v_info.get("created_at") or "")[:10] or "N/A"
                trigger = f"`{v_info.get('trigger', 'generation')}`"
                remediations = ", ".join(v_info.get("remediations") or []) or "Initial synthesis"
                eval_info = v_info.get("evaluation")
                if eval_info and "success_rate" in eval_info:
                    sr = f"{eval_info['success_rate'] * 100:.1f}% ({eval_info.get('num_episodes', 0)} eps)"
                else:
                    sr = "*Pending evaluation*"
                table_rows.append(f"| {v_num} | {created} | {trigger} | {remediations} | {sr} |")
        else:
            now_date = datetime.now(timezone.utc).isoformat()[:10]
            table_rows.append(f"| `v{current_v}` | {now_date} | `generation` | Initial synthesis | *Pending evaluation* |")

        lineage_table_str = "\n".join(table_rows)

        readme_content = f"""# Environment: `{self.env_name}` (Latest: `v{current_v}`)

> **Prompt / Task Description**:
> "{prompt}"

---

## 1. Quick Info & Artifact Paths
- **Canonical Environment Name**: `{self.env_name}`
- **Active Version Directory**: `generated_envs/{self.env_name}/latest/` (symlinked to `v{current_v}`)
- **Environment Graph Spec**: `{spec_abs_path}`
- **Policy Configuration**: `{policy_config_abs_path}`
- **Evaluation Output Directory**: `{eval_output_abs_path}`
- **Lineage Ledgers**: [`lineage.json`](./lineage.json) | [`lineage.ttl`](./lineage.ttl) (W3C PROV-O)

---

## 2. API Credentials Setup (LLM Generation & Refinement)
Before invoking the Active Bayesian environment generation agent or refinement tools, export the API key for your preferred LLM provider:

```bash
# Option A: Google Gemini
export GEMINI_API_KEY="your-gemini-api-key"

# Option B: OpenAI
export OPENAI_API_KEY="your-openai-api-key"

# Option C: NVIDIA NIM / NGC API
export NV_API_KEY="your-nv-api-key"

# Option D: OpenRouter (Claude Sonnet 4.5, Gemini 3.7, GPT-4o)
export OPENROUTER_API_KEY="your-openrouter-key"
export OPENROUTER_BASE_URL="https://openrouter.ai/api/v1"
```

---

## 3. Developer Quick-Run Commands

### A. Zero-Action Physics & Scene Verification
Verify object placement stability, kinematic reach, and contact settling in Omniverse Kit without running policy inference:

```bash
# Allow host X11 access (run once on host): xhost +local:docker
docker exec -it \\
  -e DISPLAY="$DISPLAY" \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \\
  --mode build \\
  --env_graph_spec_yaml {spec_abs_path} \\
  --num_steps 200 \\
  --viz kit
```

### B. Interactive GR00T Policy Rollout (Live Viewport)
Watch the Franka Panda robot arm execute closed-loop pick-and-place trajectories in real time:

```bash
# Allow host X11 access (run once on host): xhost +local:docker
docker exec -it \\
  -e DISPLAY="$DISPLAY" \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena/evaluation/policy_runner.py \\
  --viz kit \\
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \\
  --policy_config_yaml_path {policy_config_abs_path} \\
  --remote_host 127.0.0.1 \\
  --remote_port 5557 \\
  --num_steps 2000 \\
  --enable_cameras \\
  --env_graph_spec_yaml {spec_abs_path} \\
  --output_base_dir {eval_output_abs_path}
```

### C. Scaled Headless Benchmark (High-Throughput Parallel Flywheel)
Run tensorized parallel environments headlessly to measure empirical success and lift rates:

```bash
docker exec -it \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena/evaluation/policy_runner.py \\
  --policy_type isaaclab_arena_gr00t.policy.gr00t_remote_closedloop_policy.Gr00tRemoteClosedloopPolicy \\
  --policy_config_yaml_path {policy_config_abs_path} \\
  --remote_host 127.0.0.1 \\
  --remote_port 5557 \\
  --num_envs 32 \\
  --num_episodes 32 \\
  --num_steps 2000 \\
  --enable_cameras \\
  --env_graph_spec_yaml {spec_abs_path} \\
  --output_base_dir {eval_output_abs_path}
```

### D. Active Inference Auto-Healing
Automatically analyze failure telemetry from evaluation runs and synthesize the next remediated version `v(N+1)`:

```bash
docker exec -it \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \\
  --mode auto_heal \\
  --env_name {self.env_name}
```

### E. Conversational Refinement & Prompt Synthesis
Modify this environment with natural language feedback or generate a new sibling variant:

```bash
# Refine this environment based on feedback:
docker exec -it \\
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \\
  --mode resolve \\
  --base_spec {spec_abs_path} \\
  --feedback "Move the destination receptacle 5cm to the left and change the table surface material."

# Re-generate from initial prompt:
docker exec -it \\
  -e GEMINI_API_KEY="$GEMINI_API_KEY" \\
  isaaclab_arena-latest /isaac-sim/python.sh \\
  isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py \\
  --mode resolve \\
  --prompt "{prompt}" \\
  --env_name {self.env_name}
```

---

## 4. Version History & Remediation Lineage
| Version | Created Date | Trigger | Remediation / Patch Notes | Benchmark Outcome |
| :--- | :--- | :--- | :--- | :--- |
{lineage_table_str}
"""

        readme_file = self.env_dir / "README.md"
        with open(readme_file, "w", encoding="utf-8") as f:
            f.write(readme_content)

        return readme_file

