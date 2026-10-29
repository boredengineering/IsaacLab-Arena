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
import os
import sys
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from isaaclab_arena.agentic_environment_generation.spec_io import DEFAULT_AGENTIC_OUTPUT_DIR, write_env_graph_dict
from isaaclab_arena.cli.isaaclab_arena_cli import arena_env_builder_cfg_from_argparse, get_isaaclab_arena_cli_parser
from isaaclab_arena.utils.isaaclab_utils.simulation_app import SimulationAppContext

if TYPE_CHECKING:
    from isaaclab.envs import ManagerBasedEnv

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

DEFAULT_PROMPT = "Franka picks up a cube from the maple table and places it into a bowl on the table."


def add_agentic_env_gen_runner_cli_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("Agentic Environment Generation Runner")
    for name in (
        "api_socket",
        "api_origin",
        "store_id",
        "family",
        "operation_id",
        "publication_profile",
        "publication_revision",
        "publication",
        "publication_request_id",
        "reservation_id",
        "publication_effect_id",
        "publication_previous_request_id",
    ):
        group.add_argument(f"--managed_{name}", type=Path if name == "api_socket" else str, default=None)
    group.add_argument(
        "--mode",
        type=str,
        choices=(
            "full",
            "resolve",
            "grounded-resolve",
            "grounded_resolve",
            "build",
            "schema",
            "catalog",
            "auto_heal",
            "auto-heal",
            "workflow",
        ),
        default="full",
        help=(
            "Which phases to run: 'schema' (print the spec JSON schema and exit), "
            "'catalog' (print the agent catalog and exit), 'resolve' (prompt -> spec YAML, no Isaac Sim), "
            "'grounded-resolve' (resolve + 30-step headless PhysX settle + live VLM camera inspection), "
            "'build' (needs --env_graph_spec_yaml), 'auto_heal' (diagnose eval failures & remediate spec/policy), "
            "'workflow' (closed-loop ForegroundWorkflow + Neo4j dual-schema orchestration), "
            "or 'full' (resolve and build in one process; default). "
            "'schema' and 'catalog' make no agent call."
        ),
    )
    group.add_argument(
        "--use-orchestrator",
        "--use_orchestrator",
        dest="use_orchestrator",
        action="store_true",
        default=False,
        help="Delegate execution to ForegroundWorkflow.execute_workflow() with Neo4j dual-schema tracking.",
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
        help=(
            "Explicit API key for inference backend (default: OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, or"
            " NV_API_KEY)."
        ),
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
        "--spec_path",
        dest="base_spec",
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
    group.add_argument(
        "--strict-critics",
        "--strict_critics",
        dest="strict_critics",
        action="store_true",
        default=False,
        help="Fail fast with exit code 2 if configured LLM, VLM, or Neo4j endpoints are unreachable.",
    )
    group.add_argument(
        "--permissive",
        action="store_true",
        default=False,
        help="Bypass strict preflight infrastructure gating and allow mock/heuristic fallbacks.",
    )
    group.add_argument(
        "--ensure-infra",
        "--ensure_infra",
        dest="ensure_infra",
        action="store_true",
        default=False,
        help="Automatically verify and initiate required infrastructure (Neo4j, Spec LLM, Visual VLM) before running.",
    )
    group.add_argument(
        "--num-settle-steps",
        "--num_settle_steps",
        dest="num_settle_steps",
        type=int,
        default=60,
        help="Number of PhysX settling steps for physical equilibrium and drop detection (default: 60).",
    )


def verify_service_endpoint(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Verify that an OpenAI-compatible service endpoint responds to GET /v1/models.

    Args:
        url: Base URL of the OpenAI-compatible service (e.g. ``http://127.0.0.1:8000/v1``).
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of ``(reachable, model_id_or_error)``.
    """
    import json
    import urllib.request

    base = url.rstrip("/")
    models_url = base if base.endswith("/models") else f"{base}/models"
    req = urllib.request.Request(models_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            data_list = body.get("data", [])
            model_id = (
                str(data_list[0].get("id"))
                if data_list and isinstance(data_list[0], dict) and data_list[0].get("id")
                else "ok"
            )
            return True, model_id
    except Exception as exc:
        return False, f"Endpoint {models_url} unreachable: {exc}"


def verify_neo4j_endpoint(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    timeout: float = 3.0,
) -> tuple[bool, str]:
    """Verify that the Neo4j Graph database endpoint responds to Bolt handshake and query.

    Args:
        uri: Bolt URI (defaults to ``NEO4J_URI`` or ``bolt://127.0.0.1:7688``).
        user: Username (defaults to ``NEO4J_USER`` or ``neo4j``).
        password: Password (defaults to ``NEO4J_PASSWORD`` or ``isaaclab_arena_password``).
        timeout: Connection timeout in seconds.

    Returns:
        Tuple of ``(reachable, message)``.
    """
    import os

    uri = uri or os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")

    try:
        import neo4j
    except ImportError:
        return False, "neo4j Python package is not installed"

    try:
        driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=timeout,
            max_connection_lifetime=timeout,
        )
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 AS probe").single()
            if not result or result["probe"] != 1:
                driver.close()
                return False, f"Unexpected probe result from Neo4j at {uri}"
        driver.close()
        return True, "connected"
    except Exception as exc:
        return False, f"Neo4j endpoint {uri} unreachable: {exc}"


def check_preflight_service_triad(args_cli: argparse.Namespace) -> None:
    """Pre-flight check the full infrastructure triad (Spec LLM, Visual VLM, Neo4j) before simulation starts."""
    import os
    import sys

    # Skip preflight if purely informational modes
    if getattr(args_cli, "mode", None) in ("schema", "catalog"):
        return

    # Auto-ensure infrastructure if requested
    if getattr(args_cli, "ensure_infra", False):
        try:
            from isaaclab_arena.orchestration.infra_manager import InfraManager

            infra_mgr = InfraManager()
            infra_mgr.ensure_all_services()
        except Exception as exc:
            print(f"[WARNING][InfraManager] Auto-ensure infra encountered an issue: {exc}", flush=True)

    # Determine whether strict validation is required
    is_generation_mode = getattr(args_cli, "mode", None) in ("resolve", "grounded-resolve", "grounded_resolve", "full")
    is_permissive = getattr(args_cli, "permissive", False)
    is_strict = getattr(args_cli, "strict_critics", False) or (is_generation_mode and not is_permissive)

    llm_url = args_cli.base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    vlm_url = os.environ.get("LOCAL_VLM_BASE_URL", "http://127.0.0.1:8001/v1")
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688")

    llm_ok, llm_info = verify_service_endpoint(llm_url, timeout=2.0)
    vlm_ok, vlm_info = verify_service_endpoint(vlm_url, timeout=2.0)
    neo4j_ok, neo4j_info = verify_neo4j_endpoint(neo4j_uri, timeout=3.0)

    if is_strict:
        failed_services = []
        if not llm_ok:
            failed_services.append(f"Spec LLM ({llm_url}): {llm_info}")
        if getattr(args_cli, "mode", None) in ("grounded-resolve", "grounded_resolve", "full") and not vlm_ok:
            failed_services.append(f"Visual VLM ({vlm_url}): {vlm_info}")
        if not neo4j_ok:
            failed_services.append(f"Neo4j Experience Graph ({neo4j_uri}): {neo4j_info}")

        if failed_services:
            print("\n" + "=" * 70, file=sys.stderr)
            print("[ERROR][Preflight] Required infrastructure service(s) failed health check:", file=sys.stderr)
            for fail_msg in failed_services:
                print(f"  ❌ {fail_msg}", file=sys.stderr)
            print("\nTo start or verify all services on the host system, run:", file=sys.stderr)
            print("  python3 docker/arena_infra.py up", file=sys.stderr)
            print("To intentionally run offline without services, re-run with --permissive.", file=sys.stderr)
            print("=" * 70 + "\n", file=sys.stderr, flush=True)
            sys.exit(2)
    else:
        if not llm_ok:
            print(f"[WARNING] LLM service endpoint {llm_url} unreachable ({llm_info}); using fallback.", flush=True)
        if not vlm_ok:
            print(
                f"[WARNING] VLM service endpoint {vlm_url} unreachable ({vlm_info}); using Tier 3 geometric fallback.",
                flush=True,
            )
        if not neo4j_ok:
            print(
                f"[WARNING] Neo4j endpoint {neo4j_uri} unreachable ({neo4j_info}); proceeding without graph sync.",
                flush=True,
            )


def _build_permissive_fallback_spec(args_cli: argparse.Namespace) -> ArenaEnvGraphSpec:
    """Build a grounded deterministic fallback spec when an endpoint is unreachable in permissive mode."""
    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        _ensure_reified_relations_and_grounding,
    )
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    if getattr(args_cli, "base_spec", None) and Path(args_cli.base_spec).exists():
        spec = ArenaEnvGraphSpec.from_yaml(args_cli.base_spec)
        return _ensure_reified_relations_and_grounding(spec)

    fallback_dict = {
        "env_name": getattr(args_cli, "env_name", None) or "llm_gen_maple_table_robolab_PickAndPlaceTask",
        "embodiment": {"id": "franka_ik", "registry_name": "franka_ik"},
        "background": {"id": "maple_table_robolab", "registry_name": "maple_table_robolab"},
        "objects": [
            {"id": "rubiks_cube_hot3d_robolab", "registry_name": "rubiks_cube_hot3d_robolab"},
            {"id": "bowl_ycb_robolab", "registry_name": "bowl_ycb_robolab"},
        ],
        "relations": [
            {"kind": "is_anchor", "subject": "maple_table_robolab"},
            {
                "kind": "on",
                "subject": "rubiks_cube_hot3d_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_center"},
            },
            {
                "kind": "on",
                "subject": "bowl_ycb_robolab",
                "reference": "maple_table_robolab",
                "params": {"surface_anchor": "table_top", "surface_sector": "front_left"},
            },
        ],
        "task": {
            "composition": "atomic",
            "description": getattr(args_cli, "prompt", None) or DEFAULT_PROMPT,
            "subtasks": [{
                "kind": "PickAndPlaceTask",
                "params": {
                    "pick_up_object": "rubiks_cube_hot3d_robolab",
                    "destination_location": "bowl_ycb_robolab",
                    "background_scene": "maple_table_robolab",
                },
            }],
        },
    }
    spec = ArenaEnvGraphSpec.from_dict(fallback_dict)
    return _ensure_reified_relations_and_grounding(spec)


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

    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import diagnose_transfer_readiness
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
            f" ⚠  '{report['policy_ref']}' ({report['policy_kind']}): scene violates {report['out_of_tolerance_axes']}",
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
    import os

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        EnvironmentGenerationAgent,
        build_asset_catalogue,
        build_relation_catalogue,
        build_task_catalogue,
    )

    check_preflight_service_triad(args_cli)

    strict_critics = bool(getattr(args_cli, "strict_critics", False)) or not bool(getattr(args_cli, "permissive", False))
    llm_url = args_cli.base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    llm_ok, llm_info = verify_service_endpoint(llm_url)

    asset_catalog = build_asset_catalogue()
    relation_catalog = build_relation_catalogue()
    task_catalog = build_task_catalogue()

    agent = None
    env_graph_spec = None
    data = None
    base_spec = None

    if args_cli.base_spec:
        from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

        base_spec = ArenaEnvGraphSpec.from_yaml(args_cli.base_spec)

    if args_cli.base_url and not llm_ok and not strict_critics:
        print(
            f"[WARNING] Configured --base_url {args_cli.base_url} is unreachable; "
            "synthesizing deterministic fallback spec.",
            flush=True,
        )
        env_graph_spec = _build_permissive_fallback_spec(args_cli)
    else:
        agent_kwargs: dict = {
            "temperature": args_cli.temperature,
            "strict_mode": strict_critics,
        }
        if args_cli.model:
            agent_kwargs["model"] = args_cli.model
        elif llm_ok and llm_info != "ok" and (args_cli.base_url or "127.0.0.1" in llm_url or "localhost" in llm_url):
            agent_kwargs["model"] = llm_info
        if args_cli.base_url:
            agent_kwargs["base_url"] = args_cli.base_url
        if args_cli.api_key:
            agent_kwargs["api_key"] = args_cli.api_key
        elif args_cli.base_url and ("127.0.0.1" in args_cli.base_url or "localhost" in args_cli.base_url):
            agent_kwargs["api_key"] = "local-vllm"
        agent = EnvironmentGenerationAgent(**agent_kwargs)

        if base_spec is not None:
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
        if agent is not None:
            print("\n[runner] validation traces:", flush=True)
            for line in agent.traces:
                print(f"  {line}", flush=True)
        invalid_path = write_env_graph_dict(data, args_cli.out_dir)
        print(f"[runner] wrote invalid spec YAML to {invalid_path}", flush=True)
        assert False, f"Agent returned an invalid spec. Validation traces: {agent.traces if agent else ()}"
    print_env_graph(env_graph_spec)
    print(
        f"[runner] generated → {env_graph_spec.summary()}, env_name={env_graph_spec.env_name!r}",
        flush=True,
    )
    if agent is not None and agent.telemetry:
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


def print_policy_diagnostic_plan(diagnostic_plan: dict | None, policy_ref: str | None) -> None:
    """Print the planner's belief state and selected next steps, or say why it was skipped."""
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
            "[auto_heal] no --policy_ref and no 'checkpoint_uri' in the policy config; policy-side diagnosis skipped.",
            flush=True,
        )


def emit_policy_diagnostics_artifacts(
    spec_env_name: str,
    policy_ref: str | None,
    diagnostic_state,
    diagnostic_plan: dict | None,
    out_dir: Path,
    version: int,
) -> None:
    """Write the policy-side diagnosis as RDF, then mirror it into Neo4j if one is reachable.

    RDF first and in its own try block: it needs no server, so a missing Neo4j must not lose it.
    """
    if diagnostic_state is None or diagnostic_plan is None or not diagnostic_plan.get("profile_known"):
        return

    from isaaclab_arena.agentic_environment_generation.policy_capability_graph import get_policy_profile

    profile = get_policy_profile(policy_ref)
    if profile is None:
        return

    eval_run_id = f"{spec_env_name}_v{version}"
    try:
        from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import emit_policy_diagnostics_ttl

        ttl_path = emit_policy_diagnostics_ttl(
            out_path=str(out_dir / "policy_diagnostics.ttl"),
            env_name=spec_env_name,
            profile=profile,
            state=diagnostic_state,
            eval_run_id=eval_run_id,
            next_technique_id=diagnostic_plan["next_diagnostic"],
            remediation_id=diagnostic_plan["recommended_remediation"],
        )
        print(f"[auto_heal] 🧠 Policy diagnostics graph written to: {ttl_path}", flush=True)
    except Exception as exc:
        print(f"[auto_heal] policy diagnostics RDF emission skipped: {exc}", flush=True)

    try:
        from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import (
            sync_policy_diagnostics_to_neo4j,
        )

        sync_policy_diagnostics_to_neo4j(
            env_name=spec_env_name,
            profile=profile,
            state=diagnostic_state,
            eval_run_id=eval_run_id,
            next_technique_id=diagnostic_plan["next_diagnostic"],
            remediation_id=diagnostic_plan["recommended_remediation"],
        )
        print("[auto_heal] synced policy diagnostics to Neo4j LPG.", flush=True)
    except Exception:
        pass


def run_auto_heal(args_cli: argparse.Namespace) -> Path:
    """Diagnose evaluation telemetry and apply automated Active Inference self-healing."""
    from isaaclab_arena.agentic_environment_generation.eval_self_healing import (
        EvaluationDiagnosticOracle,
        EvaluationRemediationEngine,
    )
    from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    # 1. Resolve base spec and canonical env name
    spec_path_raw = (
        args_cli.base_spec
        or getattr(args_cli, "env_graph_spec_yaml", None)
        or getattr(args_cli, "env_spec", None)
    )
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
        from isaaclab_arena.agentic_environment_generation.eval_self_healing import build_policy_diagnostic_state

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

    print_policy_diagnostic_plan(diagnostic_plan, policy_ref)

    engine = EvaluationRemediationEngine()
    healed_spec, healed_policy_path, meta = engine.remediate_and_heal(
        spec=spec,
        policy_config_path=policy_config_path,
        signatures=signatures,
        out_dir=args_cli.out_dir,
    )

    if getattr(args_cli, "healing_mode", "hybrid") == "llm":
        try:
            from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
                EnvironmentGenerationAgent,
            )

            feedback_lines = [f"{s.defect_type}: {s.evidence}" for s in signatures]
            if feedback_lines:
                agent = EnvironmentGenerationAgent(
                    model=args_cli.model,
                    base_url=args_cli.base_url,
                    api_key=args_cli.api_key,
                    temperature=args_cli.temperature,
                )
                refined, _ = agent.refine_spec(healed_spec, feedback="\n".join(feedback_lines))
                if refined is not None:
                    healed_spec = refined
        except Exception as exc:
            print(f"[auto_heal] LLM refinement fallback to deterministic: {exc}", flush=True)

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

    emit_policy_diagnostics_artifacts(
        spec_env_name=spec.env_name,
        policy_ref=policy_ref,
        diagnostic_state=diagnostic_state,
        diagnostic_plan=diagnostic_plan,
        out_dir=new_v_dir,
        version=new_v,
    )

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


def _encode_rgb_array_to_png_bytes(rgb_array) -> bytes:
    """Encode an HxWx3 uint8 RGB array or tensor into PNG bytes."""
    import io
    import struct
    import zlib
    import numpy as np

    if hasattr(rgb_array, "detach"):
        arr = rgb_array.detach().cpu().numpy()
    else:
        arr = np.asarray(rgb_array)
    if arr.ndim == 4:
        arr = arr[0]
    if arr.dtype != np.uint8:
        arr = np.clip(arr * (255.0 if arr.max() <= 1.0 else 1.0), 0, 255).astype(np.uint8)
    if arr.shape[-1] > 3:
        arr = arr[..., :3]

    try:
        from PIL import Image

        buf = io.BytesIO()
        Image.fromarray(arr).save(buf, format="PNG")
        return buf.getvalue()
    except Exception:
        height, width, _ = arr.shape
        raw_rows = b"".join(b"\x00" + arr[y].tobytes() for y in range(height))

        def _chunk(tag: bytes, data: bytes) -> bytes:
            return (
                struct.pack("!I", len(data))
                + tag
                + data
                + struct.pack("!I", zlib.crc32(tag + data) & 0xFFFFFFFF)
            )

        ihdr = struct.pack("!IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (
            b"\x89PNG\r\n\x1a\n"
            + _chunk(b"IHDR", ihdr)
            + _chunk(b"IDAT", zlib.compress(raw_rows, 6))
            + _chunk(b"IEND", b"")
        )


def _extract_rendered_images_from_obs(obs: dict | None, env=None) -> dict[str, bytes]:
    """Extract RGB camera observations from gym obs or scene sensors as PNG byte buffers."""
    rendered: dict[str, bytes] = {}
    if isinstance(obs, dict):
        cam_obs = obs.get("camera_obs")
        if isinstance(cam_obs, dict):
            for cam_name, tensor in cam_obs.items():
                try:
                    rendered[str(cam_name)] = _encode_rgb_array_to_png_bytes(tensor)
                except Exception:
                    pass
    if not rendered and env is not None:
        base_env = getattr(env, "unwrapped", env)
        scene = getattr(base_env, "scene", None)
        sensors = getattr(scene, "sensors", {}) if scene is not None else {}
        if isinstance(sensors, dict):
            for cam_name, sensor in sensors.items():
                try:
                    rgb = getattr(getattr(sensor, "data", None), "output", {}).get("rgb")
                    if rgb is not None:
                        rendered[str(cam_name)] = _encode_rgb_array_to_png_bytes(rgb)
                except Exception:
                    pass
    return rendered


def _settle_and_capture_frames(
    spec: ArenaEnvGraphSpec,
    args_cli: argparse.Namespace,
    num_settle_steps: int = 30,
    keep_env: bool = False,
    existing_env: Any = None,
    old_spec: ArenaEnvGraphSpec | None = None,
) -> tuple[bool, list[str], dict[str, bytes], Any]:
    """Run a 30-step headless PhysX settle, detect object drops/displacement, and capture camera PNGs.

    When called outside a live Omniverse runtime, falls back to static geometric/physical preflight checks.
    """
    from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import validate_spatial_geometry
    from isaaclab_arena.agentic_environment_generation.visual_critic import PhysXPreflightCritic

    try:
        import torch
        import warp as wp
        from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager
        from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
        from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg
        from isaaclab_arena.video.video_recording import VideoRecordingCfg, wrap_env_for_video

        canonical_env_name = getattr(args_cli, "env_name", None) or spec.env_name
        mgr_probe = EnvironmentVersionManager(canonical_env_name)
        curr_v = max(mgr_probe.get_latest_version(), 1)

        if existing_env is None:
            arena_env = spec.to_arena_env(enable_cameras=True)
            builder = ArenaEnvBuilder(arena_env, arena_env_builder_cfg_from_argparse(args_cli))
            video_dir = Path("eval_output") / canonical_env_name / f"v{curr_v}" / "videos"
            video_dir.mkdir(parents=True, exist_ok=True)
            video_cfg = VideoRecordingCfg(
                record_viewport_video=True,
                record_camera_video=True,
                video_base_dir=str(video_dir),
            )
            env = builder.make_registered(render_mode=video_cfg.render_mode)
            if video_cfg.enabled:
                env = wrap_env_for_video(env, video_cfg, max(num_settle_steps, 30), None)
            obs, _ = env.reset()
        else:
            env = existing_env
            base_env = env.unwrapped
            scene = base_env.scene
            if old_spec is not None:
                for obj in spec.objects:
                    old_obj = next((o for o in old_spec.objects if o.id == obj.id), None)
                    if old_obj and obj.id in scene.keys():
                        old_pos = old_obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.0, 0.0])
                        new_pos = obj.params.get("initial_pose", {}).get("position_xyz", [0.0, 0.0, 0.0])
                        dx = float(new_pos[0] - old_pos[0])
                        dy = float(new_pos[1] - old_pos[1])
                        dz = float(new_pos[2] - old_pos[2])
                        if abs(dx) > 1e-4 or abs(dy) > 1e-4 or abs(dz) > 1e-4:
                            asset = scene[obj.id]
                            new_pose = asset.data.root_state_w[:, :7].clone()
                            new_pose[0, 0] += dx
                            new_pose[0, 1] += dy
                            new_pose[0, 2] += dz
                            asset.write_root_pose_to_sim(new_pose)
                            zero_vel = torch.zeros((1, 6), device=base_env.device)
                            asset.write_root_velocity_to_sim(zero_vel)
            obs = None

        try:
            base_env = env.unwrapped
            scene = base_env.scene
            policy = ZeroActionPolicy(ZeroActionPolicyCfg())
            if obs is None:
                policy.reset()
                zero_act = torch.zeros(env.action_space.shape, device=base_env.device)
                with torch.inference_mode():
                    obs, _, _, _, _ = env.step(zero_act)

            init_positions: dict[str, list[float]] = {}
            for obj in spec.objects:
                if obj.id in scene.keys():
                    asset = scene[obj.id]
                    if hasattr(asset, "data") and hasattr(asset.data, "root_pos_w"):
                        pos_t = wp.to_torch(asset.data.root_pos_w)[0, :3].detach().cpu().tolist()
                        init_positions[obj.id] = [float(c) for c in pos_t]

            settle_issues: list[str] = []
            for step_idx in range(max(num_settle_steps, 30)):
                with torch.inference_mode():
                    action = policy.get_action(env, obs)
                    obs, _, terminated, truncated, _ = env.step(action)
                if (terminated | truncated).any():
                    settle_issues.append(
                        f"PhysX settle terminated prematurely at step {step_idx} (< {num_settle_steps}) due to"
                        " instability/drop."
                    )
                    break

            for obj_id, init_xyz in init_positions.items():
                asset = scene[obj_id]
                final_xyz = [
                    float(c)
                    for c in wp.to_torch(asset.data.root_pos_w)[0, :3].detach().cpu().tolist()
                ]
                disp = sum((final_xyz[i] - init_xyz[i]) ** 2 for i in range(3)) ** 0.5
                drop_threshold_z = init_xyz[2] - 0.20
                if final_xyz[2] < drop_threshold_z or disp > 0.15:
                    settle_issues.append(
                        f"Object '{obj_id}' unstable during {num_settle_steps}-step PhysX settle: "
                        f"displaced {disp:.3f}m from {[round(c, 3) for c in init_xyz]} to "
                        f"{[round(c, 3) for c in final_xyz]}."
                    )

            rendered_images = _extract_rendered_images_from_obs(obs, env=env)
            is_ok = len(settle_issues) == 0
            if is_ok and keep_env:
                return True, settle_issues, rendered_images, env
            if not keep_env:
                try:
                    env.close()
                except Exception:
                    pass
                return is_ok, settle_issues, rendered_images, None
            return is_ok, settle_issues, rendered_images, env
        except Exception as e:
            if not keep_env:
                try:
                    env.close()
                except Exception:
                    pass
            raise e
    except Exception as e:
        import traceback
        print(f"[_settle_and_capture_frames] Caught exception: {e}", flush=True)
        traceback.print_exc()
        phys_issues = list(PhysXPreflightCritic().evaluate_physical_stability(spec))
        geom_ok, geom_errs = validate_spatial_geometry(spec)
        if not geom_ok:
            phys_issues.extend(geom_errs)
        return len(phys_issues) == 0, phys_issues, {}, None


def run_grounded_resolve(args_cli: argparse.Namespace, return_live_env: bool = False) -> Path | tuple[Path, Any]:
    """Resolve an environment spec and verify it via 30-step PhysX settling and Step-0 VLM inspection."""
    import os

    from isaaclab_arena.agentic_environment_generation.environment_generation_agent import (
        EnvironmentGenerationAgent,
        _deterministic_affordance_fallback,
    )
    from isaaclab_arena.agentic_environment_generation.telemetry import ActiveInferenceTelemetry
    from isaaclab_arena.agentic_environment_generation.version_manager import EnvironmentVersionManager
    from isaaclab_arena.agentic_environment_generation.visual_critic import VisualSceneCritic
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    spec_path = resolve_env_spec(args_cli)
    spec = ArenaEnvGraphSpec.from_yaml(spec_path)
    args_cli.enable_cameras = True
    args_cli.headless = True
    strict_critics = bool(getattr(args_cli, "strict_critics", False))
    num_settle_steps = max(int(getattr(args_cli, "num_settle_steps", 60)), 60)
    max_grounded_repairs = 3
    live_env = None
    active_env = None
    old_spec = None

    for repair_idx in range(max_grounded_repairs):
        settled_ok, settle_issues, rendered_images, candidate_env = _settle_and_capture_frames(
            spec,
            args_cli,
            num_settle_steps=num_settle_steps,
            keep_env=True,
            existing_env=active_env,
            old_spec=old_spec,
        )
        active_env = candidate_env

        canonical_env_name = getattr(args_cli, "env_name", None) or spec.env_name
        mgr = EnvironmentVersionManager(canonical_env_name)
        curr_v = max(mgr.get_latest_version(), 1)

        # Persist Step-0 camera frames to eval_output and generated_envs
        eval_photo_dir = Path("eval_output") / canonical_env_name / f"v{curr_v}" / "photos"
        eval_photo_dir.mkdir(parents=True, exist_ok=True)
        gen_photo_dir = Path("generated_envs") / canonical_env_name / f"v{curr_v}" / "photos"
        gen_photo_dir.mkdir(parents=True, exist_ok=True)
        latest_photo_dir = Path("eval_output") / canonical_env_name / "photos"
        latest_photo_dir.mkdir(parents=True, exist_ok=True)

        for cam_name, img_bytes in rendered_images.items():
            for pdir in (eval_photo_dir, gen_photo_dir, latest_photo_dir):
                target_p = pdir / f"{cam_name}.png"
                with open(target_p, "wb") as f:
                    f.write(img_bytes)
            print(f"[step-0-audit] 📸 Saved step-0 visual audit image → {eval_photo_dir / f'{cam_name}.png'}", flush=True)

        critic = VisualSceneCritic(strict_mode=strict_critics)
        visual_res = critic.evaluate_scene_spec(
            spec,
            rendered_images=rendered_images if rendered_images else None,
        )

        has_frames = bool(rendered_images)
        vis_status = (
            "Failed"
            if not visual_res.conforms
            else (
                "Passed (Tier 1 Cloud)"
                if has_frames and visual_res.tier_used == "tier_1_cloud_vlm"
                else (
                    "Passed (Tier 2 Local VLM)"
                    if has_frames and visual_res.tier_used == "tier_2_local_vlm"
                    else (
                        "Passed (Tier 3 Geometric)"
                        if has_frames
                        else "Bypassed (No Frames - Tier 3 Fallback)"
                    )
                )
            )
        )
        phys_status = "Passed (30-step PhysX)" if settled_ok and has_frames else (
            "Failed (Drop Detected)" if not settled_ok else "Passed (AABB Heuristic)"
        )
        grade = (
            "GOLD: Grounded & Visually Verified"
            if settled_ok
            and visual_res.conforms
            and has_frames
            and visual_res.tier_used in ("tier_1_cloud_vlm", "tier_2_local_vlm")
            else ("SILVER: Geometric & Semantic Only" if settled_ok and visual_res.conforms else "PROVISIONAL: Unverified Settle")
        )
        telemetry_card = ActiveInferenceTelemetry(
            model=getattr(args_cli, "model", None) or "grounded-resolve",
            repair_iterations=repair_idx,
            converged=settled_ok and visual_res.conforms,
            shacl_passed=True,
            geometry_passed=settled_ok,
            visual_critic_tier=visual_res.tier_used,
            visual_critic_status=vis_status,
            physics_preflight_status=phys_status,
            verification_grade=grade,
        )
        print("\n" + telemetry_card.render_summary_card() + "\n", flush=True)

        if settled_ok and visual_res.conforms:
            live_env = active_env
            break

        feedback_parts: list[str] = []
        if settle_issues:
            feedback_parts.append("PHYSX SETTLE FAILURES:\n" + "\n".join(settle_issues))
        if not visual_res.conforms:
            anom_text = "\n".join(visual_res.anomalies)
            feedback_parts.append(
                f"STEP-0 VLM VISUAL CRITIC ({visual_res.tier_used}):\n{anom_text}\n{visual_res.actionable_feedback}"
            )
        combined_feedback = "\n\n".join(feedback_parts)
        print(
            f"[grounded-resolve] Iteration {repair_idx + 1}: Refining spec from grounded feedback:\n{combined_feedback}",
            flush=True,
        )

        llm_url = args_cli.base_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
        llm_ok, llm_info = verify_service_endpoint(llm_url)
        old_spec = spec
        if llm_ok:
            agent = EnvironmentGenerationAgent(
                model=args_cli.model or (llm_info if llm_info != "ok" else None),
                base_url=args_cli.base_url or llm_url,
                api_key=args_cli.api_key or "local-vllm",
                temperature=getattr(args_cli, "temperature", 0.2),
                strict_mode=strict_critics,
            )
            refined_spec, _ = agent.refine_spec(
                spec,
                feedback=combined_feedback,
                rendered_images=rendered_images if rendered_images else None,
            )
            if refined_spec is not None:
                spec = refined_spec
            else:
                spec = _deterministic_affordance_fallback(spec, strict_mode=strict_critics)
        else:
            spec = _deterministic_affordance_fallback(spec, strict_mode=strict_critics)

        canonical_env_name = getattr(args_cli, "env_name", None) or spec.env_name
        mgr = EnvironmentVersionManager(canonical_env_name)
        new_v, _ = mgr.create_version(
            spec_source=spec,
            trigger="grounded_resolve",
            prompt=combined_feedback,
        )
        spec_path = mgr.get_spec_yaml_path(new_v)
        print(f"[grounded-resolve] Saved refined grounded spec (v{new_v}) → {spec_path}", flush=True)

    if return_live_env:
        return spec_path, live_env or active_env
    if active_env is not None:
        try:
            active_env.close()
        except Exception:
            pass
    return spec_path


def build_env_from_env_graph_spec(env_graph_spec_path: Path, args_cli: argparse.Namespace) -> ManagerBasedEnv:
    """Build a gymnasium env from an environment graph spec YAML."""
    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
    from isaaclab_arena.environments.arena_env_builder import ArenaEnvBuilder
    from isaaclab_arena.video.video_recording import VideoRecordingCfg, wrap_env_for_video

    loaded_env_graph_spec = ArenaEnvGraphSpec.from_yaml(env_graph_spec_path)
    enable_cams = bool(
        getattr(args_cli, "enable_cameras", False)
        or getattr(args_cli, "record_camera_video", False)
        or getattr(args_cli, "mode", None) in ("grounded-resolve", "grounded_resolve", "build", "full")
    )
    arena_env = loaded_env_graph_spec.to_arena_env(enable_cameras=enable_cams)
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

        rendered_images = _extract_rendered_images_from_obs(None, env=env)
        critic = VisualSceneCritic(strict_mode=bool(getattr(args_cli, "strict_critics", False)))
        critic_result = critic.evaluate_scene_spec(
            loaded_env_graph_spec,
            rendered_images=rendered_images if rendered_images else None,
        )
        print("\n======================================================================", flush=True)
        print(f"  👁️  Preflight Visual Critic Inspection (Tier: {critic_result.tier_used})", flush=True)
        print("======================================================================", flush=True)
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
        print("======================================================================\n", flush=True)
    except Exception as exc:
        if getattr(args_cli, "strict_critics", False):
            raise
        print(f"[runner] Preflight visual critic check skipped: {exc}", flush=True)

    return env


def run_zero_action_policy(env: ManagerBasedEnv, num_steps: int) -> None:
    """Run the zero-action policy for a given number of steps."""
    import torch

    from isaaclab_arena.policy.zero_action_policy import ZeroActionPolicy, ZeroActionPolicyCfg

    policy = ZeroActionPolicy(ZeroActionPolicyCfg())
    with torch.inference_mode():
        obs, _ = env.reset()
        policy.reset()
        for step in range(num_steps):
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
    path_arg = getattr(args_cli, "env_graph_spec_yaml", None) or getattr(args_cli, "env_spec", None)
    assert path_arg is not None, "--mode build requires --env_graph_spec_yaml or --env_spec"
    path = Path(path_arg)
    assert path.is_file(), f"env graph spec YAML not found: {path}"
    return path


def main(*, on_build_completed: Callable[[], None] | None = None) -> int:
    """Run the CLI lifecycle with an optional trusted Python-only build hook.

    Args:
        on_build_completed: Called after the build rollout returns, before simulator
            shutdown (which may terminate the process). Unused outside build mode.

    Returns:
        The exit code when the lifecycle returns normally.
    """
    parser = get_isaaclab_arena_cli_parser()
    add_agentic_env_gen_runner_cli_args(parser)
    args_cli = parser.parse_args()

    if any(
        getattr(args_cli, f"managed_{name}") is not None
        for name in (
            "api_socket",
            "api_origin",
            "store_id",
            "family",
            "operation_id",
            "publication_profile",
            "publication_revision",
            "publication",
            "publication_request_id",
            "reservation_id",
            "publication_effect_id",
            "publication_previous_request_id",
        )
    ):
        from isaaclab_arena_examples.agentic_environment_generation.managed_workflow_cli import run_managed

        return run_managed(args_cli, argv=sys.argv[1:])

    check_preflight_service_triad(args_cli)

    if args_cli.mode == "schema":
        print_schema()
        return 0

    if args_cli.mode == "catalog":
        print_catalog()
        return 0

    if args_cli.mode == "resolve":
        resolve_env_spec(args_cli)
        return 0

    if os.environ.get("CUDA_VISIBLE_DEVICES") in ("1", "cuda:1"):
        # When GPU 1 is isolated via CUDA_VISIBLE_DEVICES, it is the sole device (index 0)
        args_cli.device = "cuda:0"
        existing_kit = getattr(args_cli, "kit_args", "") or ""
        if "--/app/window/adapter" not in existing_kit:
            args_cli.kit_args = f"{existing_kit} --/app/window/adapter=0 --/renderer/activeGpu=0".strip()
    elif getattr(args_cli, "device", None) in ("cuda:1", "1"):
        args_cli.device = "cuda:1"
        existing_kit = getattr(args_cli, "kit_args", "") or ""
        if "--/app/window/adapter" not in existing_kit:
            args_cli.kit_args = f"{existing_kit} --/app/window/adapter=1 --/renderer/activeGpu=1".strip()

    if args_cli.mode in ("grounded-resolve", "grounded_resolve", "full"):
        args_cli.enable_cameras = True
        args_cli.headless = True
        args_cli.no_solve_relations = True

    if args_cli.mode in ("grounded-resolve", "grounded_resolve"):
        with SimulationAppContext(args_cli):
            run_grounded_resolve(args_cli, return_live_env=False)
        return 0

    if args_cli.mode in ("auto_heal", "auto-heal"):
        run_auto_heal(args_cli)
        return 0

    if args_cli.mode == "workflow" or getattr(args_cli, "use_orchestrator", False):
        from isaaclab_arena_examples.agentic_environment_generation.foreground_workflow import (
            execute_operational_workflow,
        )

        result = execute_operational_workflow(
            prompt=args_cli.prompt,
            num_settle_steps=getattr(args_cli, "num_settle_steps", 60),
            run_rollout=args_cli.mode == "full",
        )
        accepted_spec = result.get("accepted_spec_dict")
        if accepted_spec and getattr(args_cli, "out_dir", None) is not None:
            env_name = args_cli.env_name or accepted_spec.get("name", "generated_env")
            out_path = Path(args_cli.out_dir) / f"{env_name}_env_graph.yaml"
            write_env_graph_dict(accepted_spec, out_path)
            print(
                f"[runner] Orchestrated workflow finished ({result['final_state']}); saved spec to {out_path}",
                flush=True,
            )
        return 0 if result.get("final_state") == "accepted" else 1

    if args_cli.mode == "build":
        spec_path = _resolved_graph_spec_yaml(args_cli)
        # Pre-flight before the simulator starts: an invariant violation costs arithmetic to
        # detect here and a full rollout to detect later.
        check_transfer_readiness(spec_path, resolve_policy_ref(args_cli, args_cli.policy_config))
        with SimulationAppContext(args_cli):
            build_env_and_run_policy(spec_path, args_cli)
            if on_build_completed is not None:
                on_build_completed()
        return 0

    args_cli.enable_cameras = True
    with SimulationAppContext(args_cli):
        env_graph_spec_path, live_env = run_grounded_resolve(args_cli, return_live_env=True)
        # In 'full' mode the spec is now physically settled, visually audited by VLM, and certified
        # before running transfer readiness and policy rollout.
        check_transfer_readiness(env_graph_spec_path, resolve_policy_ref(args_cli, args_cli.policy_config))
        if live_env is not None:
            print("[runner] Executing policy rollout on the verified, live environment...", flush=True)
            run_zero_action_policy(live_env, args_cli.num_steps)
        else:
            build_env_and_run_policy(env_graph_spec_path, args_cli)
    return 0


if __name__ == "__main__":
    sys.exit(main())
