# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""End-to-end agentic environment generation and execution.

Usage::

    # Print the Pydantic ArenaEnvGraphSpec JSON schema (no agent call, no Isaac Sim):
    python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode schema

    # Print the catalog sent to the agent (no agent call, no Isaac Sim):
    python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode catalog

    # Resolve a prompt into an environment graph spec YAML (no Isaac Sim):
    python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode resolve --prompt ...

    # Build a gym env from a graph spec YAML and run the zero-action policy:
    python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode build --headless \\
        --num_envs 1 --env_graph_spec_yaml <env>_env_graph.yaml

    # Resolve and build in one process:
    python isaaclab_arena_examples/agentic_environment_generation/environment_generation_runner.py --mode full --headless \\
        --num_envs 1 --prompt ...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from isaaclab_arena.agentic_environment_generation.spec_io import (
    DEFAULT_AGENTIC_OUTPUT_DIR,
    write_env_graph_dict,
    write_env_graph_spec,
)
from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

DEFAULT_PROMPT = "Franka picks up a cube from the maple table and places it into a bowl on the table."


def add_agentic_env_gen_runner_cli_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Agentic Environment Generation Runner")
    group.add_argument(
        "--mode",
        type=str,
        choices=("full", "resolve", "build", "schema", "catalog", "auto_heal"),
        default="full",
        help=(
            "Which phases to run: 'schema' (print the spec JSON schema and exit), "
            "'catalog' (print the agent catalog and exit), 'resolve' (prompt -> spec YAML, no Isaac Sim), "
            "'build' (needs --env_graph_spec_yaml), 'auto_heal' (diagnose eval failures & remediate spec/policy), "
            "or 'full' (resolve and build in one process; default). "
            "'schema' and 'catalog' make no agent call."
        ),
    )
    group.add_argument(
        "--eval_dir",
        type=Path,
        default=None,
        help="Path to an evaluation output directory containing eval_telemetry.ttl / summary_metrics.json.",
    )
    group.add_argument(
        "--policy_config",
        type=Path,
        default=None,
        help="Path to the policy configuration YAML used during evaluation.",
    )
    group.add_argument(
        "--prompt",
        type=str,
        default=DEFAULT_PROMPT,
        help="Natural-language env description passed to the generation agent.",
    )
    group.add_argument(
        "--model",
        type=str,
        default=None,
        help="Override the LLM model id (default: agent's built-in default).",
    )
    group.add_argument(
        "--base_url",
        type=str,
        default=None,
        help="Override the LLM base URL endpoint (default: env var or built-in default).",
    )
    group.add_argument(
        "--temperature",
        type=float,
        default=0.2,
        help="LLM sampling temperature (default: 0.2).",
    )
    group.add_argument(
        "--num_steps",
        type=int,
        default=20,
        help="Number of simulation steps to run with the zero-action policy (default: 20).",
    )
    group.add_argument(
        "--out_dir",
        type=Path,
        default=DEFAULT_AGENTIC_OUTPUT_DIR,
        help="Directory for the generated YAML files (default: isaaclab_arena_environments/agent_generated).",
    )
    group.add_argument(
        "--api_key",
        type=str,
        default=None,
        help="Explicit API key for inference backend (default: NV_API_KEY, GEMINI_API_KEY, or OPENAI_API_KEY).",
    )
    group.add_argument(
        "--env_name",
        type=str,
        default=None,
        help="Canonical environment family name for versioned tracking (default: inferred from prompt or spec).",
    )
    group.add_argument(
        "--version",
        type=int,
        default=None,
        help="Explicit version number to load or evaluate (default: latest version).",
    )
    group.add_argument(
        "--base_spec",
        type=Path,
        default=None,
        help="Path to an existing ArenaEnvGraphSpec YAML to refine or continue from.",
    )
    group.add_argument(
        "--healing_mode",
        type=str,
        choices=("hybrid", "deterministic", "llm"),
        default="hybrid",
        help=(
            "Active Inference self-healing mode: 'deterministic' (Option A: rule-based/spatial factor graph oracle), "
            "'llm' (Option B: generative LLM reasoning via OpenRouter/Gemini), or "
            "'hybrid' (Option A first with automatic Option B LLM fallback; default)."
        ),
    )
    group.add_argument(
        "--feedback",
        type=str,
        default=None,
        help="Natural-language instructions describing what to change in --base_spec.",
    )
    group.add_argument(
        "--record_viewport_video",
        action="store_true",
        default=False,
        help="Record an mp4 video of the rollout viewport (uses gymnasium.wrappers.RecordVideo).",
    )
    group.add_argument(
        "--record_camera_video",
        action="store_true",
        default=False,
        help="Record one mp4 per camera in obs['camera_obs'].",
    )
    group.add_argument(
        "--policy_ref",
        type=str,
        default=None,
        help=(
            "Policy profile id or checkpoint URI the environment will be evaluated against "
            "(e.g. 'nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace'). Enables the transfer-readiness "
            "pre-flight check and policy-side diagnosis. Falls back to 'checkpoint_uri' in the "
            "policy config YAML when omitted; without either, policy-side checks are skipped "
            "because the graph cannot tell which policy is in play."
        ),
    )


def resolve_policy_ref(args_cli: argparse.Namespace, policy_config_path: Path | str | None = None) -> str | None:
    """Resolve the policy reference from the CLI, else from the policy config's ``checkpoint_uri``.

    The checkpoint identity lives in the GR00T server's ``--model-path``, outside the graph, so
    without one of these two sources the policy-side machinery has nothing to key on.
    """
    if getattr(args_cli, "policy_ref", None):
        return args_cli.policy_ref
    if policy_config_path and Path(policy_config_path).exists():
        import yaml

        try:
            config = yaml.safe_load(Path(policy_config_path).read_text(encoding="utf-8")) or {}
        except Exception:
            return None
        return config.get("checkpoint_uri") or config.get("model_path")
    return None


def check_transfer_readiness(spec_path: Path, policy_ref: str | None) -> dict | None:
    """Report whether a scene lies inside the target policy's training invariants.

    Warns and never blocks: the check is only as trustworthy as its declared tolerances, which are
    provisional. Returns the report, or None when no policy reference was resolvable.
    """
    if not policy_ref:
        return None

    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
        diagnose_transfer_readiness,
    )
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    report = diagnose_transfer_readiness(ArenaEnvGraphSpec.from_yaml(spec_path), policy_ref)
    print("\n" + "=" * 70, flush=True)
    print(" 🛫 TRANSFER READINESS PRE-FLIGHT", flush=True)
    print("=" * 70, flush=True)
    if not report.get("profile_known"):
        print(f" {report.get('message')}", flush=True)
        print("=" * 70 + "\n", flush=True)
        return report

    if report["transfer_expected"]:
        print(f" ✅ '{report['policy_ref']}': scene is within every declared training invariant.", flush=True)
    else:
        print(
            f" ⚠  '{report['policy_ref']}' ({report['policy_kind']}): scene violates "
            f"{report['out_of_tolerance_axes']}",
            flush=True,
        )
        print(f"    Worst departure: {report['worst_shift_sigma']}x tolerance", flush=True)
        print(f"    Dominant failure mode: {report['dominant_failure_mode']}", flush=True)
        for shift in report["shifts"]:
            if not shift["within_tolerance"]:
                print(f"    - {shift['axis']}: {shift['evidence']}", flush=True)
        print(f"    Scene-preserving fix: {report['scene_preserving_remediation']}", flush=True)
        print(f"    Scene-changing fix:   {report['scene_changing_remediation']}", flush=True)
        print("    (warning only - the rollout proceeds)", flush=True)
    print("=" * 70 + "\n", flush=True)
    return report


def resolve_env_spec(args_cli: argparse.Namespace) -> Path:
    """Resolve a prompt into an environment graph spec YAML."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        EnvironmentGenerationAgent,
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    asset_catalog = build_asset_catalogue()
    relation_catalog = build_relation_catalogue()
    task_catalog = build_task_catalogue()

    agent_kwargs: dict = {"temperature": args_cli.temperature}
    if args_cli.model:
        agent_kwargs["model"] = args_cli.model
    if args_cli.base_url:
        agent_kwargs["base_url"] = args_cli.base_url
    if args_cli.api_key:
        agent_kwargs["api_key"] = args_cli.api_key
    agent = EnvironmentGenerationAgent(**agent_kwargs)

    if args_cli.base_spec:
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        base_spec = ArenaEnvGraphSpec.from_yaml(args_cli.base_spec)
        refinement_prompt = args_cli.feedback or args_cli.prompt
        print(f"\n[runner] refining base spec '{args_cli.base_spec}' with feedback: {refinement_prompt!r}", flush=True)
        env_graph_spec, data = agent.refine_spec(
            base_spec,
            feedback=refinement_prompt,
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
        )
    else:
        print(f"\n[runner] prompt: {args_cli.prompt!r}", flush=True)
        env_graph_spec, data = agent.generate_spec(
            args_cli.prompt,
            asset_catalog=asset_catalog,
            relation_catalog=relation_catalog,
            task_catalog=task_catalog,
        )
    # agent.traces holds one line per failure, e.g.
    #   "embodiment.registry_name: Unknown asset registry_name 'not_a_real_asset'"
    #   "Task 'PickAndPlaceTask' is missing required param 'pick_up_object'"
    if env_graph_spec is None:
        print("\n[runner] validation traces:", flush=True)
        for line in agent.traces:
            print(f"  {line}", flush=True)
        invalid_path = write_env_graph_dict(data, args_cli.out_dir)
        print(f"[runner] wrote invalid spec YAML to {invalid_path}", flush=True)
        assert False, f"Agent returned an invalid spec. Validation traces: {agent.traces}"
    print_env_graph(env_graph_spec)
    print(
        f"[runner] generated → {env_graph_spec.summary()}, env_name={env_graph_spec.env_name!r}",
        flush=True,
    )
    if agent.telemetry:
        print("\n" + agent.telemetry.render_summary_card() + "\n", flush=True)

    canonical_env_name = args_cli.env_name or env_graph_spec.env_name
    from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager

    mgr = EnvironmentVersionManager(canonical_env_name)
    new_v, new_v_dir = mgr.create_version(
        spec_source=env_graph_spec,
        trigger="active_inference_refinement" if args_cli.base_spec else "initial_generation",
        prompt=args_cli.feedback or args_cli.prompt,
    )
    path = mgr.get_spec_yaml_path(new_v)
    print(f"[runner] wrote environment graph spec (version v{new_v}) → {path}", flush=True)
    print(f"[runner] lineage ledger updated at: {mgr.lineage_file}", flush=True)

    # Optional Neo4j LPG synchronization (Phase 4)
    try:
        from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j

        parent_name = base_spec.env_name if args_cli.base_spec else None
        feedback_txt = args_cli.feedback or args_cli.prompt if args_cli.base_spec else None
        lpg_summary = sync_spec_to_neo4j(
            env_graph_spec,
            telemetry=agent.telemetry,
            parent_env_name=parent_name,
            derivation_feedback=feedback_txt,
        )
        print(
            f"[runner] synced to Neo4j LPG → {lpg_summary.get('node_count', 0)} nodes, "
            f"{lpg_summary.get('rel_count', 0)} relations",
            flush=True,
        )
    except Exception:
        pass

    return path


def run_auto_heal(args_cli: argparse.Namespace) -> Path:
    """Diagnose evaluation telemetry and apply automated Active Inference self-healing."""
    from isaaclab_arena.agentic_environment_generation.eval_self_healing import (
        EvaluationDiagnosticOracle,
        EvaluationRemediationEngine,
    )
    from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    # 1. Resolve base spec and canonical env name
    spec_path_raw = args_cli.base_spec or args_cli.env_graph_spec_yaml
    canonical_env_name = args_cli.env_name

    if spec_path_raw is None and canonical_env_name is not None:
        mgr_probe = EnvironmentVersionManager(canonical_env_name)
        target_v = args_cli.version or mgr_probe.get_latest_version()
        if target_v > 0:
            spec_path_raw = mgr_probe.get_spec_yaml_path(target_v)
            print(f"[auto_heal] inferred base spec for {canonical_env_name} v{target_v}: {spec_path_raw}", flush=True)

    assert spec_path_raw is not None, "--mode auto_heal requires --base_spec, --env_graph_spec_yaml, or --env_name"
    spec_path = Path(spec_path_raw)
    spec = ArenaEnvGraphSpec.from_yaml(spec_path)
    if not canonical_env_name:
        canonical_env_name = spec.env_name

    mgr = EnvironmentVersionManager(canonical_env_name)

    # 2. Locate eval dir
    eval_dir = args_cli.eval_dir
    if not eval_dir:
        latest_v = mgr.get_latest_version()
        candidate_eval = mgr.get_eval_dir(latest_v)
        if candidate_eval.exists():
            eval_dir = candidate_eval
            print(f"[auto_heal] discovered versioned eval run directory: {eval_dir}", flush=True)
        else:
            eval_root = Path("eval_output")
            runs = sorted(eval_root.glob("*/*"), key=lambda p: p.stat().st_mtime, reverse=True)
            if runs:
                eval_dir = runs[0]
                print(f"[auto_heal] discovered most recent eval run directory: {eval_dir}", flush=True)
            else:
                raise FileNotFoundError("No eval_output directory found. Provide --eval_dir.")
    else:
        eval_dir = Path(eval_dir)

    # 3. Locate policy config
    policy_config_path = args_cli.policy_config
    if not policy_config_path:
        v_policy = mgr.get_policy_config_path()
        if v_policy and v_policy.exists():
            policy_config_path = v_policy
        else:
            default_policy = Path("isaaclab_arena_gr00t/policy/config/droid_manip_gr00t_closedloop_config.yaml")
            if default_policy.exists():
                policy_config_path = default_policy
        print(f"[auto_heal] using policy config: {policy_config_path}", flush=True)

    oracle = EvaluationDiagnosticOracle()
    signatures = oracle.diagnose_eval_run(
        eval_dir=eval_dir,
        spec=spec,
        policy_config_path=policy_config_path,
        num_steps_executed=args_cli.num_steps if args_cli.num_steps > 20 else 500,
        healing_mode=getattr(args_cli, "healing_mode", "hybrid"),
        api_key=args_cli.api_key,
        model=args_cli.model,
        base_url=args_cli.base_url,
        temperature=args_cli.temperature,
    )

    # Fuse the oracle's behavioural signatures with spec-level distribution shifts into one belief
    # state, and report what the planner would measure and change next. Reporting only for now --
    # the planner's tolerances are provisional until the Phase 1 sweep measures them, so it does
    # not yet select the remediation that gets applied below.
    policy_ref = resolve_policy_ref(args_cli, policy_config_path)
    diagnostic_state, diagnostic_plan = (None, None)
    if policy_ref:
        from isaaclab_arena.agentic_environment_generation.eval_self_healing import (
            build_policy_diagnostic_state,
        )

        diagnostic_state, diagnostic_plan = build_policy_diagnostic_state(
            spec=spec,
            policy_ref=policy_ref,
            signatures=signatures,
        )

    print("\n" + "=" * 70, flush=True)
    print(" 🩺 EVALUATION DIAGNOSTIC ORACLE REPORT", flush=True)
    print("=" * 70, flush=True)
    for idx, sig in enumerate(signatures, 1):
        print(f"[{idx}] Defect Type: {sig.defect_type.upper()} (Severity: {sig.severity:.2f})", flush=True)
        print(f"    Evidence: {sig.evidence}", flush=True)
        if sig.recommended_policy_patches:
            print(f"    Policy Patch: {sig.recommended_policy_patches}", flush=True)
        if sig.recommended_spatial_patches:
            print(f"    Spatial Patch: {sig.recommended_spatial_patches}", flush=True)
    print("=" * 70 + "\n", flush=True)

    if diagnostic_plan is not None and diagnostic_plan.get("profile_known"):
        print("=" * 70, flush=True)
        print(" 🧠 POLICY DIAGNOSTIC PLANNER", flush=True)
        print("=" * 70, flush=True)
        print(f" Policy: {diagnostic_plan['policy_ref']}", flush=True)
        if diagnostic_plan["out_of_tolerance_axes"]:
            print(f" Invariants violated: {diagnostic_plan['out_of_tolerance_axes']}", flush=True)
        print(
            f" Dominant failure mode: {diagnostic_plan['dominant_failure_mode']} "
            f"(belief {diagnostic_plan['dominant_belief']})",
            flush=True,
        )
        print(f" Next diagnostic to run: {diagnostic_plan['next_diagnostic']}", flush=True)
        print(f" Recommended remediation: {diagnostic_plan['recommended_remediation']}", flush=True)
        for mode_id, belief in list(diagnostic_plan["beliefs"].items())[:5]:
            print(f"   - {mode_id}: {belief}", flush=True)
        print("=" * 70 + "\n", flush=True)
    elif policy_ref:
        print(
            f"[auto_heal] no registered policy profile for {policy_ref!r}; policy-side diagnosis skipped.",
            flush=True,
        )
    else:
        print(
            "[auto_heal] no --policy_ref and no 'checkpoint_uri' in the policy config; "
            "policy-side diagnosis skipped.",
            flush=True,
        )

    engine = EvaluationRemediationEngine()
    healed_spec, healed_policy_path, meta = engine.remediate_and_heal(
        spec=spec,
        policy_config_path=policy_config_path,
        signatures=signatures,
        out_dir=args_cli.out_dir,
    )

    # Create next structured version snapshot
    remediation_summaries = []
    for s in signatures:
        if s.recommended_spatial_patches:
            remediation_summaries.append(f"Spatial: {s.recommended_spatial_patches}")
        if s.recommended_policy_patches:
            remediation_summaries.append(f"Policy: {s.recommended_policy_patches}")
    if not remediation_summaries:
        remediation_summaries.append("Evaluated and adjusted hyperparameters for next rollout iteration.")

    new_v, new_v_dir = mgr.create_version(
        spec_source=healed_spec,
        policy_config_source=healed_policy_path,
        trigger="active_inference_auto_heal",
        parent_version=mgr.get_latest_version(),
        remediations=remediation_summaries,
        diagnostics=[f"{s.defect_type}: {s.evidence}" for s in signatures],
    )

    healed_spec_path = mgr.get_spec_yaml_path(new_v)
    healed_policy_final = mgr.get_policy_config_path(new_v)

    print(f"[auto_heal] ✅ Healed environment spec saved (v{new_v}) → {healed_spec_path}", flush=True)
    print(f"[auto_heal] ✅ Healed policy config saved (v{new_v})  → {healed_policy_final}", flush=True)
    print(f"[auto_heal] 🚀 Recommended rollout steps: {meta.get('recommended_steps', 2000)}", flush=True)
    print(f"[auto_heal] 📜 Lineage ledger updated at: {mgr.lineage_file}", flush=True)

    # Emit the policy-side diagnosis as RDF next to the version snapshot. Written before the
    # Neo4j attempt because it needs no server and should not be lost when Neo4j is unavailable.
    if diagnostic_state is not None and diagnostic_plan is not None and diagnostic_plan.get("profile_known"):
        try:
            from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
                get_policy_profile,
            )
            from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import (
                emit_policy_diagnostics_ttl,
            )

            profile = get_policy_profile(policy_ref)
            if profile is not None:
                ttl_path = emit_policy_diagnostics_ttl(
                    out_path=str(new_v_dir / "policy_diagnostics.ttl"),
                    env_name=spec.env_name,
                    profile=profile,
                    state=diagnostic_state,
                    eval_run_id=f"{spec.env_name}_v{new_v}",
                    next_technique_id=diagnostic_plan["next_diagnostic"],
                    remediation_id=diagnostic_plan["recommended_remediation"],
                )
                print(f"[auto_heal] 🧠 Policy diagnostics graph written to: {ttl_path}", flush=True)
        except Exception as exc:
            print(f"[auto_heal] policy diagnostics RDF emission skipped: {exc}", flush=True)

    # Sync lineage derivation to Neo4j if available
    try:
        from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import sync_spec_to_neo4j

        defect_summary = ", ".join(s.defect_type for s in signatures)
        sync_spec_to_neo4j(
            healed_spec,
            parent_env_name=spec.env_name,
            derivation_feedback=f"Auto-healed v{new_v} from failure: {defect_summary}",
        )
        print("[auto_heal] synced lineage derivation to Neo4j LPG.", flush=True)
    except Exception:
        pass

    if diagnostic_state is not None and diagnostic_plan is not None and diagnostic_plan.get("profile_known"):
        try:
            from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
                get_policy_profile,
            )
            from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import (
                sync_policy_diagnostics_to_neo4j,
            )

            profile = get_policy_profile(policy_ref)
            if profile is not None:
                sync_policy_diagnostics_to_neo4j(
                    env_name=spec.env_name,
                    profile=profile,
                    state=diagnostic_state,
                    eval_run_id=f"{spec.env_name}_v{new_v}",
                    next_technique_id=diagnostic_plan["next_diagnostic"],
                    remediation_id=diagnostic_plan["recommended_remediation"],
                )
                print("[auto_heal] synced policy diagnostics to Neo4j LPG.", flush=True)
        except Exception:
            pass

    return healed_spec_path


def print_schema() -> None:
    """Print the Pydantic ArenaEnvGraphSpec JSON schema."""
    import json

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    print(json.dumps(ArenaEnvGraphSpec.model_json_schema(), indent=2))


def print_catalog() -> None:
    """Print the asset, relation, and task catalogs sent to the agent."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    print(build_asset_catalogue().to_catalog_string())
    print()
    print(build_relation_catalogue().to_catalog_string())
    print()
    print(build_task_catalogue().to_catalog_string())


def _iter_printable_assets(spec: ArenaEnvGraphSpec):
    yield "embodiment", spec.embodiment.id, spec.embodiment.registry_name, spec.embodiment.params
    yield "background", spec.background.id, spec.background.registry_name, spec.background.params
    for obj in spec.objects:
        yield "object", obj.id, obj.registry_name, obj.params


def print_env_graph(spec: ArenaEnvGraphSpec) -> None:
    """Print the generated graph in a human-readable tabular layout."""
    print(f"\n=== ArenaEnvGraphSpec (env_name={spec.env_name!r}) ===")

    print("\nassets:")
    for role, asset_id, registry_name, params in _iter_printable_assets(spec):
        params_str = f"  params={params}" if params else ""
        print(f"  {asset_id:24s} role={role:18s} registry_name={registry_name}{params_str}")

    if spec.object_references:
        print("\nobject_references:")
        for ref in spec.object_references:
            params_str = f"  params={ref.params}" if ref.params else ""
            print(f"  {ref.id:24s} parent={ref.parent_id}  prim_path={ref.prim_path}{params_str}")

    print("\nrelations:")
    for relation in spec.relations:
        ref_str = f"  reference={relation.reference}" if relation.reference is not None else ""
        params_str = f"  params={relation.params}" if relation.params else ""
        print(f"  {relation.kind:16s} subject={relation.subject}{ref_str}{params_str}")

    print(f"\ntask: composition={spec.task.composition}")
    print(f"  description: {spec.task.description}")
    for i, task in enumerate(spec.task.subtasks):
        print(f"  [{i}] kind={task.kind}")
        print(f"    params: {task.params}")


def build_env_from_env_graph_spec(env_graph_spec_path: Path, args_cli: argparse.Namespace) -> ManagerBasedEnv:
    """Build a gymnasium env from an environment graph spec YAML."""
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.video.video_recording import VideoRecordingCfg, wrap_env_for_video

    loaded_env_graph_spec = ArenaEnvGraphSpec.from_yaml(env_graph_spec_path)
    arena_env = loaded_env_graph_spec.to_arena_env()
    # TODO(cvolk, 2026-07-06): [typed-config-migration] Pass ArenaEnvBuilderCfg into this function after this
    # runner stops carrying all configuration in one argparse Namespace.
    video_cfg = VideoRecordingCfg(
        record_viewport_video=getattr(args_cli, "record_viewport_video", False),
        record_camera_video=getattr(args_cli, "record_camera_video", False),
        video_base_dir=str(args_cli.out_dir / "videos" if hasattr(args_cli, "out_dir") else "videos"),
    )
    builder = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli))
    env = builder.make_registered(render_mode=video_cfg.render_mode)
    if video_cfg.enabled:
        env = wrap_env_for_video(env, video_cfg, args_cli.num_steps, None)
    print(
        f"[runner] built env {arena_env.name!r} from environment graph spec {env_graph_spec_path}",
        flush=True,
    )

    # Preflight visual verification pass across cascading perception tiers
    try:
        from isaaclab_arena.agentic_environment_generation.visual_critic import VisualSceneCritic

        critic = VisualSceneCritic()
        critic_result = critic.evaluate_scene_spec(loaded_env_graph_spec)
        print(f"\n======================================================================", flush=True)
        print(f"  👁️  Preflight Visual Critic Inspection (Tier: {critic_result.tier_used})", flush=True)
        print(f"======================================================================", flush=True)
        print(f"• Conforms:         {'✅ PASS' if critic_result.conforms else '⚠️ ANOMALIES DETECTED'}", flush=True)
        print(f"• Visibility Score: {critic_result.visibility_score:.1f} / 10.0", flush=True)
        if critic_result.occluded_objects:
            print(f"• Occluded Objects: {', '.join(critic_result.occluded_objects)}", flush=True)
        if critic_result.floating_objects:
            print(f"• Floating Objects: {', '.join(critic_result.floating_objects)}", flush=True)
        if critic_result.anomalies:
            print("• Detected Anomalies:", flush=True)
            for anom in critic_result.anomalies:
                print(f"  - {anom}", flush=True)
        if critic_result.actionable_feedback and not critic_result.conforms:
            print(f"• Actionable Advice: {critic_result.actionable_feedback}", flush=True)
        print(f"======================================================================\n", flush=True)
    except Exception as exc:
        print(f"[runner] Preflight visual critic check skipped: {exc}", flush=True)

    return env


def run_zero_action_policy(env: ManagerBasedEnv, num_steps: int) -> None:
    """Run the zero-action policy for a given number of steps."""
    import torch

    from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg

    policy = ZeroActionPolicy(ZeroActionPolicyCfg())
    obs, _ = env.reset()
    policy.reset()
    for step in range(num_steps):
        with torch.inference_mode():
            action = policy.get_action(env, obs)
            obs, _, terminated, truncated, _ = env.step(action)
        if (terminated | truncated).any():
            env_ids = (terminated | truncated).nonzero().flatten()
            print(f"[runner] step {step}: episode done for env_ids {env_ids.tolist()}", flush=True)
            policy.reset(env_ids=env_ids)
    env.close()
    print("[runner] done.", flush=True)


def build_env_and_run_policy(env_graph_spec_path: Path, args_cli: argparse.Namespace) -> None:
    """Build the gym env from a graph spec YAML and run the zero-action policy."""
    env = build_env_from_env_graph_spec(env_graph_spec_path, args_cli)
    run_zero_action_policy(env, args_cli.num_steps)


def _resolved_graph_spec_yaml(args_cli: argparse.Namespace) -> Path:
    path_arg = args_cli.env_graph_spec_yaml
    assert path_arg is not None, "--mode build requires --env_graph_spec_yaml"
    path = Path(path_arg)
    assert path.is_file(), f"env graph spec YAML not found: {path}"
    return path


def main() -> int:
    parser = get_isaaclab_arena_cli_parser()
    add_agentic_env_gen_runner_cli_args(parser)
    args_cli = parser.parse_args()

    if args_cli.mode == "schema":
        print_schema()
        return 0

    if args_cli.mode == "catalog":
        print_catalog()
        return 0

    if args_cli.mode == "resolve":
        resolve_env_spec(args_cli)
        return 0

    if args_cli.mode == "auto_heal":
        run_auto_heal(args_cli)
        return 0

    if args_cli.mode == "build":
        spec_path = _resolved_graph_spec_yaml(args_cli)
        # Pre-flight before the simulator starts: an invariant violation costs arithmetic to
        # detect here and a full rollout to detect later.
        check_transfer_readiness(spec_path, resolve_policy_ref(args_cli, args_cli.policy_config))
        with SimulationAppContext(args_cli):
            build_env_and_run_policy(spec_path, args_cli)
        return 0

    with SimulationAppContext(args_cli):
        env_graph_spec_path = resolve_env_spec(args_cli)
        # In 'full' mode the spec does not exist until the agent resolves it, so the check runs
        # here rather than before the app starts. It still precedes env construction and rollout.
        check_transfer_readiness(env_graph_spec_path, resolve_policy_ref(args_cli, args_cli.policy_config))
        build_env_and_run_policy(env_graph_spec_path, args_cli)
    return 0


if __name__ == "__main__":
    sys.exit(main())
