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
