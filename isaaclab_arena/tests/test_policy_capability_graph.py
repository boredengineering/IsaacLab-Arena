# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for the policy capability graph, its planner, and its RDF projection.

Shift measurement reads only attribute names off the spec, so these tests build lightweight stubs
rather than a full ``ArenaEnvGraphSpec``. That keeps them runnable without Isaac Sim; one test at
the end exercises the real spec type and skips where the simulator is unavailable.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
import pytest
import rdflib

from isaaclab_arena.agentic_environment_generation.policy_capability_graph import (
    DIAGNOSTIC_TECHNIQUES,
    FAILURE_MODES,
    REMEDIATION_TECHNIQUES,
    SIM_TO_REAL_INVARIANTS,
    DiagnosticCapabilities,
    PolicyDiagnosticState,
    ProbeObservation,
    compute_distribution_shifts,
    diagnose_transfer_readiness,
    get_policy_profile,
    plan_diagnostic_sequence,
    rank_remediations,
    select_next_diagnostic,
    select_remediation,
)
from isaaclab_arena.agentic_environment_generation.policy_diagnostics_sync import (
    ARENA,
    emit_distribution_shifts_rdf,
    emit_policy_profile_rdf,
    emit_technique_catalogue_rdf,
    query_blocking_shifts,
)
GN1X = "nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace"


@dataclass
class _AssetStub:
    id: str
    registry_name: str
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class _TaskStub:
    description: str


@dataclass
class _SpecStub:
    env_name: str
    embodiment: Any
    background: Any
    objects: list[Any]
    task: Any
    relations: list[Any] = field(default_factory=list)


def _asset(asset_id: str, registry_name: str, position: list[float] | None = None) -> _AssetStub:
    params = {"initial_pose": {"position_xyz": position, "rotation_xyzw": [0, 0, 0, 1]}} if position else {}
    return _AssetStub(id=asset_id, registry_name=registry_name, params=params)


def _tabletop_spec() -> _SpecStub:
    """Scenario C1 as actually built: maple table at chest height, manipuland front-right."""
    return _SpecStub(
        env_name="g1_tabletop_apple_to_plate",
        embodiment=_asset("g1", "g1_wbc_agile_joint", [-0.46, 0.0, 0.0]),
        background=_asset("maple_table", "maple_table_robolab"),
        objects=[
            _asset("red_apple", "apple_01_objaverse_robolab", [0.0798, -0.3199, 0.7818]),
            _asset("clay_plate", "clay_plate_robolab", [0.1133, 0.2542, 0.7527]),
        ],
        task=_TaskStub("Reach with the right arm to grasp the red apple and place it onto the clay plate"),
    )


def _corpus_aligned_spec() -> _SpecStub:
    """The same task laid out to match every one of the corpus invariants."""
    return _SpecStub(
        env_name="galileo_g1_static_pick_and_place",
        embodiment=_asset("g1", "g1_wbc_agile_joint", [-0.46, 0.0, 0.0]),
        background=_asset("shelf", "galileo_locomanip_warehouse_shelf"),
        objects=[
            # 0.75 pelvis offset - 0.8015 corpus height puts the manipuland at the trained elevation.
            _asset("red_apple", "apple_01_objaverse_robolab", [0.0, 0.199, -0.0515]),
            _asset("clay_plate", "clay_plate_robolab", [0.0, -0.02, -0.0515]),
        ],
        task=_TaskStub("move the apple to the plate"),
    )


# ---------------------------------------------------------------------------
# Registry integrity
# ---------------------------------------------------------------------------


def test_every_technique_references_known_failure_modes():
    """A technique pointing at a missing mode would silently never fire."""
    for technique in DIAGNOSTIC_TECHNIQUES.values():
        for mode_id in technique.discriminates:
            assert mode_id in FAILURE_MODES, f"{technique.technique_id} discriminates unknown mode {mode_id!r}"
    for remediation in REMEDIATION_TECHNIQUES.values():
        for mode_id in remediation.resolves:
            assert mode_id in FAILURE_MODES, f"{remediation.technique_id} resolves unknown mode {mode_id!r}"
        for invariant in remediation.invalidated_by:
            assert invariant in SIM_TO_REAL_INVARIANTS, f"{remediation.technique_id} cites unknown {invariant!r}"
    for mode in FAILURE_MODES.values():
        for excluded in mode.excludes:
            assert excluded in FAILURE_MODES, f"{mode.mode_id} excludes unknown mode {excluded!r}"


def test_every_failure_mode_has_a_diagnostic_and_a_remediation():
    """An unobservable or unfixable mode cannot participate in the loop."""
    diagnosable = {mode_id for t in DIAGNOSTIC_TECHNIQUES.values() for mode_id in t.discriminates}
    fixable = {mode_id for r in REMEDIATION_TECHNIQUES.values() for mode_id in r.resolves}
    assert not set(FAILURE_MODES) - diagnosable, f"no diagnostic for {set(FAILURE_MODES) - diagnosable}"
    assert not set(FAILURE_MODES) - fixable, f"no remediation for {set(FAILURE_MODES) - fixable}"


def test_friction_inflation_is_registered_but_inadmissible():
    """The sim-to-real invariant must disqualify friction inflation rather than omit it."""
    friction = REMEDIATION_TECHNIQUES["inflate_asset_friction"]
    assert friction.invalidated_by == ("immutable_material_properties",)
    assert friction.expected_efficacy > 0.5, "it does work in sim; that is exactly why it must stay listed"

    state = PolicyDiagnosticState()
    state.beliefs = {mode_id: 0.01 for mode_id in FAILURE_MODES}
    state.beliefs["in_flight_slip_inertia"] = 0.95

    default = select_remediation(state)
    assert default is not None and default[0].technique_id != "inflate_asset_friction"

    permitted = select_remediation(state, allow_invalidated=True)
    assert permitted is not None and permitted[0].technique_id == "inflate_asset_friction"


# ---------------------------------------------------------------------------
# Shift measurement
# ---------------------------------------------------------------------------


def test_tabletop_scene_is_out_of_distribution_on_the_documented_axes():
    """The measured shifts must reproduce the C1 autopsy from the spec alone."""
    profile = get_policy_profile(GN1X)
    assert profile is not None
    shifts = {shift.axis: shift for shift in compute_distribution_shifts(_tabletop_spec(), profile)}

    height = shifts["surface_height_rel_pelvis"]
    assert not height.within_tolerance
    # Corpus fixed the manipuland ~80 cm below the pelvis; the maple table puts it at pelvis level.
    assert height.magnitude == pytest.approx(0.833, abs=0.02)
    assert height.sigma > 5.0

    assert shifts["arm_laterality"].scene_value == "right"
    assert not shifts["arm_laterality"].within_tolerance
    assert not shifts["prompt_template"].within_tolerance
    assert not shifts["visual_domain"].within_tolerance
    # The one axis v6 onward got right, and the graph should say so rather than flagging everything.
    assert shifts["controller_binding"].within_tolerance


def test_corpus_aligned_scene_reports_no_blocking_shift():
    """A layout that honours every invariant must come back clean, or the check is vacuous."""
    profile = get_policy_profile(GN1X)
    shifts = compute_distribution_shifts(_corpus_aligned_spec(), profile)
    blocking = [shift.axis for shift in shifts if not shift.within_tolerance]
    assert not blocking, f"corpus-aligned scene flagged on {blocking}"


def test_unregistered_policy_reports_unknown_rather_than_guessing():
    """Without declared invariants there is nothing to measure, and saying so beats inventing it."""
    report = diagnose_transfer_readiness(_tabletop_spec(), "some/unregistered-checkpoint")
    assert report["profile_known"] is False
    assert "shifts" not in report


# ---------------------------------------------------------------------------
# Belief update and planning
# ---------------------------------------------------------------------------


def test_shift_severity_drives_the_dominant_failure_mode():
    profile = get_policy_profile(GN1X)
    state = PolicyDiagnosticState()
    state.seed_from_shifts(compute_distribution_shifts(_tabletop_spec(), profile))

    dominant = state.dominant()
    assert dominant is not None
    assert dominant[0] == "vertical_reach_ood"
    assert state.beliefs["vertical_reach_ood"] > FAILURE_MODES["vertical_reach_ood"].prior
    # Nothing observed bears on transport dynamics, so that prior must not have moved.
    assert state.beliefs["in_flight_slip_inertia"] == pytest.approx(
        FAILURE_MODES["in_flight_slip_inertia"].prior
    )


def test_refuting_evidence_lowers_belief():
    state = PolicyDiagnosticState()
    before = state.beliefs["vision_domain_ood"]
    state.apply_observations([
        ProbeObservation(
            metric="action_delta_under_image_ablation",
            value=3.2,
            technique_id="vision_ablation_sensitivity",
            refutes=("vision_domain_ood", "policy_output_collapse"),
            likelihood_ratio=8.0,
        )
    ])
    assert state.beliefs["vision_domain_ood"] < before
    assert "vision_ablation_sensitivity" in state.applied_techniques


def test_planner_prefers_cheap_information_and_does_not_repeat_itself():
    profile = get_policy_profile(GN1X)
    state = PolicyDiagnosticState()
    state.seed_from_shifts(compute_distribution_shifts(_tabletop_spec(), profile))

    spec_only = DiagnosticCapabilities()
    plan = plan_diagnostic_sequence(state, spec_only, max_techniques=4)
    assert plan, "planner found nothing runnable from the spec alone"
    assert len(plan) == len({technique.technique_id for technique in plan})
    for technique in plan:
        assert not technique.requires_rollout
        assert not technique.requires_policy_weights

    # The first pick should be among the cheapest runnable options, not merely any of them.
    runnable = [t for t in DIAGNOSTIC_TECHNIQUES.values() if t.is_runnable(spec_only)]
    assert plan[0].cost == pytest.approx(min(t.cost for t in runnable))


def test_capabilities_gate_which_techniques_are_offered():
    state = PolicyDiagnosticState()

    remote_server = DiagnosticCapabilities(has_rollout_artifacts=True)
    selection = select_next_diagnostic(state, remote_server)
    assert selection is not None
    assert not selection[0].requires_policy_weights, "probes need in-process weights, not a remote server"

    in_process = DiagnosticCapabilities(has_policy_weights=True, has_rollout_artifacts=True, has_gpu=True)
    offered = {
        t.technique_id
        for t in DIAGNOSTIC_TECHNIQUES.values()
        if t.is_runnable(in_process) and not t.is_runnable(remote_server)
    }
    assert "vision_ablation_sensitivity" in offered


def test_false_success_is_diagnosed_by_the_cheapest_technique():
    """The v9 trap should be caught by the consistency check, not by a GPU depth audit."""
    state = PolicyDiagnosticState()
    state.beliefs = {mode_id: 0.01 for mode_id in FAILURE_MODES}
    state.beliefs["harness_false_success"] = 0.5

    selection = select_next_diagnostic(state, DiagnosticCapabilities(has_rollout_artifacts=True))
    assert selection is not None
    assert selection[0].technique_id == "success_progress_consistency_check"

    remediation = select_remediation(state)
    assert remediation is not None
    assert remediation[0].technique_id == "sequential_success_gate"
    assert remediation[0].patch == {"require_lift_before_place": True, "min_lift_height": 0.05}


def test_remediation_respects_the_scene_preserving_constraint():
    """Keeping the target scene must exclude fixes that work by rebuilding it as the corpus."""
    profile = get_policy_profile(GN1X)
    state = PolicyDiagnosticState()
    state.seed_from_shifts(compute_distribution_shifts(_tabletop_spec(), profile))

    changing = select_remediation(state, preserve_target_scene=False)
    preserving = select_remediation(state, preserve_target_scene=True)
    assert changing is not None and preserving is not None
    assert changing[0].technique_id == "reanchor_surface_to_corpus_height"
    assert changing[0].preserves_target_scene is False
    assert preserving[0].preserves_target_scene is True

    ranked = rank_remediations(state, preserve_target_scene=True)
    assert all(technique.preserves_target_scene for technique, _ in ranked)
    assert "collect_demos_and_finetune" in {technique.technique_id for technique, _ in ranked}


def test_remediation_targets_the_dominant_mode():
    """Cost normalisation must not let a cheap fix for a minor mode outrank the actual cause."""
    state = PolicyDiagnosticState()
    state.beliefs = {mode_id: 0.02 for mode_id in FAILURE_MODES}
    state.beliefs["vertical_reach_ood"] = 0.9

    targeted = select_remediation(state, require_dominant=True)
    assert targeted is not None
    assert "vertical_reach_ood" in targeted[0].resolves


# ---------------------------------------------------------------------------
# Graph projection
# ---------------------------------------------------------------------------


def test_technique_catalogue_projects_onto_rdf():
    graph = emit_technique_catalogue_rdf()
    modes = set(graph.subjects(rdflib.RDF.type, ARENA.FailureMode))
    assert len(modes) == len(FAILURE_MODES)
    probes = set(graph.subjects(rdflib.RDF.type, ARENA.ActivationProbe))
    assert probes, "activation probes must be typed as such so queries can filter on them"
    assert set(graph.subject_objects(ARENA.invalidatedBy)), "invalidated remediations must carry the edge"


def test_out_of_tolerance_shift_emits_the_violates_invariant_edge():
    """The scene-to-model bridge edge is what downstream queries traverse; it must be present."""
    profile = get_policy_profile(GN1X)
    spec = _tabletop_spec()
    shifts = compute_distribution_shifts(spec, profile)

    graph = emit_technique_catalogue_rdf()
    emit_policy_profile_rdf(profile, graph)
    emit_distribution_shifts_rdf(spec.env_name, profile, shifts, graph)

    scene_uri = rdflib.URIRef(f"https://isaac-sim.github.io/arena/instances/{spec.env_name}")
    violated = list(graph.objects(scene_uri, ARENA.violatesInvariant))
    assert violated, "no arena:violatesInvariant edge emitted for an out-of-distribution scene"
    axes = {str(next(graph.objects(inv, ARENA.invariantAxis), "")) for inv in violated}
    assert "surface_height_rel_pelvis" in axes

    # Only blocking shifts assert a violation; in-tolerance axes must not.
    assert "controller_binding" not in axes


def test_blocking_shift_query_joins_shifts_to_admissible_remediations():
    profile = get_policy_profile(GN1X)
    spec = _tabletop_spec()
    graph = emit_technique_catalogue_rdf()
    emit_policy_profile_rdf(profile, graph)
    emit_distribution_shifts_rdf(spec.env_name, profile, compute_distribution_shifts(spec, profile), graph)

    rows = query_blocking_shifts(graph)
    assert rows, "SPARQL returned no blocking shifts for an out-of-distribution scene"
    assert rows[0]["axis"] == "surface_height_rel_pelvis", "results should be ordered by severity"
    remediations = {row["remediation"] for row in rows if row["remediation"]}
    assert remediations, "blocking shifts should join through to at least one admissible remediation"


def test_shift_measurement_accepts_a_real_arena_env_graph_spec():
    """The stubs above mirror the real spec's surface; confirm that against the real type."""
    pytest.importorskip("isaaclab", reason="requires the Isaac Sim container")

    from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

    spec = ArenaEnvGraphSpec.from_dict({
        "env_name": "g1_tabletop_apple_to_plate",
        "embodiment": {
            "id": "g1",
            "registry_name": "g1_wbc_agile_joint",
            "params": {"initial_pose": {"position_xyz": [-0.46, 0.0, 0.0], "rotation_xyzw": [0, 0, 0, 1]}},
        },
        "background": {"id": "maple_table", "registry_name": "maple_table_robolab"},
        "objects": [
            {
                "id": "red_apple",
                "registry_name": "apple_01_objaverse_robolab",
                "params": {"initial_pose": {"position_xyz": [0.0798, -0.3199, 0.7818], "rotation_xyzw": [0, 0, 0, 1]}},
            },
        ],
        "relations": [],
        "task": {
            "composition": "atomic",
            "description": "Reach with the right arm to grasp the red apple",
            "subtasks": [{"kind": "PickAndPlaceTask", "params": {}}],
        },
    })

    shifts = {shift.axis for shift in compute_distribution_shifts(spec, get_policy_profile(GN1X))}
    assert "surface_height_rel_pelvis" in shifts
    assert "visual_domain" in shifts
