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
    KINEMATIC_MANIFOLDS,
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
    resolve_manifold_for_offset,
    resolve_support_relation,
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
class _RelationStub:
    kind: str
    subject: str
    reference: str | None = None
    params: dict[str, Any] = field(default_factory=dict)


@dataclass
class _ReifiedStub:
    source_id: str
    relation_type: str
    target_id: str
    kinematic_manifold: str | None = None


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
    reified_relations: list[Any] | None = None


def _relational_spec(
    fixture_registry: str,
    sector: str | None = None,
    nominal_height: float | None = None,
    manifold: str | None = None,
    object_pose: list[float] | None = None,
) -> _SpecStub:
    """A scene whose manipuland position comes from its support relation, as generated envs do."""
    params: dict[str, Any] = {}
    if sector:
        params["surface_sector"] = sector
    if nominal_height is not None:
        params["nominal_height"] = nominal_height
    return _SpecStub(
        env_name="relational_scene",
        embodiment=_asset("g1", "g1_wbc_agile_joint", [-0.46, 0.0, 0.0]),
        background=_asset("support", fixture_registry),
        objects=[_asset("red_apple", "apple_01_objaverse_robolab", object_pose)],
        task=_TaskStub("move the apple to the plate"),
        relations=[_RelationStub(kind="on", subject="red_apple", reference="support", params=params)],
        reified_relations=(
            [_ReifiedStub("red_apple", "PLACED_ON", "support", kinematic_manifold=manifold)] if manifold else None
        ),
    )


def _asset(asset_id: str, registry_name: str, position: list[float] | None = None) -> _AssetStub:
    params = {"initial_pose": {"position_xyz": position, "rotation_xyzw": [0, 0, 0, 1]}} if position else {}
    return _AssetStub(id=asset_id, registry_name=registry_name, params=params)


def _tabletop_spec() -> _SpecStub:
    """Scenario C1 as actually built, using positions MEASURED in the running scene.

    Earlier versions of this stub used a world-frame apple z of 0.7818 against a robot root at
    z=0.0, which implied the apple sat 0.78 m above the pelvis. That was the frame error the C1
    autopsy inherited. The values below come from measure_embodiment_frames.py against the real
    v9 environment: the robot root is declared at z=0.0007 and the apple settles at world
    z=0.07032, i.e. roughly at pelvis height.
    """
    return _SpecStub(
        env_name="g1_tabletop_apple_to_plate",
        embodiment=_asset("g1", "g1_wbc_agile_joint", [-0.46, 0.0, 0.0007]),
        background=_asset("maple_table", "maple_table_robolab"),
        objects=[
            _asset("red_apple", "apple_01_objaverse_robolab", [-0.09396, 0.05867, 0.07032]),
            _asset("clay_plate", "clay_plate_robolab", [-0.14346, 0.02099, 0.0066]),
        ],
        task=_TaskStub("Reach with the right arm to grasp the red apple and place it onto the clay plate"),
    )


def _corpus_aligned_spec() -> _SpecStub:
    """The same task laid out to match every corpus invariant, using MEASURED positions.

    From measure_embodiment_frames.py on galileo_g1_static_pick_and_place: robot root/pelvis at
    world z=-0.0445, apple at z=-0.00457, i.e. +0.0399 relative to the pelvis.
    """
    return _SpecStub(
        env_name="galileo_g1_static_pick_and_place",
        embodiment=_asset("g1", "g1_wbc_agile_joint", [0.24289, 0.077, -0.0445]),
        background=_asset("shelf", "galileo_locomanip_warehouse_shelf"),
        objects=[
            _asset("red_apple", "apple_01_objaverse_robolab", [0.57806, 0.23175, -0.00457]),
            _asset("clay_plate", "clay_plate_robolab", [0.57849, 0.05998, -0.02974]),
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
    """Which C1 axes are actually violated, once the frames are measured rather than assumed.

    The original autopsy reported an 80 cm vertical gap. Measurement showed the two scenes differ
    by ~6.5 cm in support height, so **height is in tolerance** and the violations are laterality,
    prompt wording, and visual domain. This test pins that corrected reading.
    """
    profile = get_policy_profile(GN1X)
    assert profile is not None
    shifts = {shift.axis: shift for shift in compute_distribution_shifts(_tabletop_spec(), profile)}

    height = shifts["surface_height_rel_pelvis"]
    assert height.within_tolerance, f"height should no longer be blocking: {height.evidence}"
    assert abs(height.magnitude) < 0.10
    assert "kinematic_manifold" not in shifts, "both scenes share one reach envelope"

    # The measured layout places the apple slightly LEFT of the base centreline, matching the
    # corpus. The "right arm" in the C1 specification is in the task *text*, not the built layout.
    assert shifts["arm_laterality"].scene_value == "left"
    assert shifts["arm_laterality"].within_tolerance

    # What is actually still violated, once height and laterality are measured rather than assumed.
    assert not shifts["prompt_template"].within_tolerance
    assert not shifts["visual_domain"].within_tolerance
    # And the axis v6 onward got right; the graph should say so rather than flagging everything.
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
# Support-relation resolution
# ---------------------------------------------------------------------------


def test_support_relation_resolves_from_declared_nominal_height():
    """An explicit nominal_height wins, matching the object placer's precedence."""
    spec = _relational_spec("maple_table_robolab", sector="front_left", nominal_height=0.42)
    support = resolve_support_relation(spec)

    assert support is not None
    assert support.height_source == "nominal_height"
    assert support.surface_z == pytest.approx(0.42)
    # The G1's articulation root is its pelvis, so a root at z=0 puts the pelvis at z=0 and the
    # offset equals the surface height itself.
    assert support.offset_rel_frame == pytest.approx(0.42)


def test_support_relation_resolves_from_a_named_shelf_tier():
    """A sector name resolves through the same table the placer reads, with no object pose at all."""
    spec = _relational_spec("galileo_locomanip", sector="shelf_tier_3")
    support = resolve_support_relation(spec)

    assert support is not None
    assert support.height_source == "surface_sector"
    assert support.anchor_name == "shelf_tier_3"
    # FIXTURE_SECTOR_BOUNDS declares shelf_tier_3 at +0.90.
    assert support.surface_z == pytest.approx(0.90)
    assert support.offset_rel_frame == pytest.approx(0.90)


def test_support_relation_prefers_the_relation_over_an_explicit_pose():
    """Where both exist the relation wins, because the placer derives the pose from it."""
    spec = _relational_spec(
        "galileo_locomanip", sector="shelf_tier_1", object_pose=[0.0, 0.199, 0.7818]
    )
    support = resolve_support_relation(spec)
    assert support.height_source == "surface_sector"
    assert support.surface_z == pytest.approx(-0.03)


def test_unresolvable_support_height_is_reported_not_invented():
    """An under-determined spec must say so rather than defaulting to zero and ranking on it."""
    spec = _relational_spec("some_unknown_fixture", sector="mystery_shelf")
    support = resolve_support_relation(spec)

    assert support is not None
    assert support.height_source == "unresolved"
    assert support.surface_z is None
    assert support.offset_rel_frame is None

    shifts = {s.axis: s for s in compute_distribution_shifts(spec, get_policy_profile(GN1X))}
    height = shifts["surface_height_rel_pelvis"]
    assert height.scene_value == "unresolved"
    assert height.manifests_as == (), "an unresolved axis must not raise belief in any failure mode"


def test_support_relation_measured_against_a_named_frame():
    """The offset is frame-relative; asking for the shoulder frame changes the answer."""
    spec = _relational_spec("galileo_locomanip", sector="shelf_tier_3")
    pelvis = resolve_support_relation(spec, embodiment_frame="pelvis")
    shoulder = resolve_support_relation(spec, embodiment_frame="shoulder")
    base = resolve_support_relation(spec, embodiment_frame="base")

    # The shoulder sits 0.292 m above the pelvis, which the root coincides with on the G1, so the
    # shoulder-relative offset is lower and base and pelvis agree.
    assert pelvis.offset_rel_frame > shoulder.offset_rel_frame
    assert shoulder.offset_rel_frame == pytest.approx(0.90 - 0.292)
    assert base.offset_rel_frame == pytest.approx(pelvis.offset_rel_frame)
    assert base.offset_rel_frame == pytest.approx(0.90)


def test_corpus_height_tier_reports_no_blocking_shift():
    """The galileo tier_1 deck is the corpus condition, so it must come back clean.

    tier_1 sits at -0.03, and the measured corpus invariant is +0.040 -- a 0.07 m departure, inside
    the (still unmeasured) 0.15 m tolerance.
    """
    spec = _relational_spec("galileo_locomanip", sector="shelf_tier_1")
    shifts = compute_distribution_shifts(spec, get_policy_profile(GN1X))
    height = next(s for s in shifts if s.axis == "surface_height_rel_pelvis")
    assert height.within_tolerance, height.evidence
    assert not any(s.axis == "kinematic_manifold" for s in shifts)


# ---------------------------------------------------------------------------
# Kinematic manifolds
# ---------------------------------------------------------------------------


def test_manifold_envelopes_classify_the_sweep_conditions():
    assert resolve_manifold_for_offset(-0.78) == "low_shelf_reach_down"
    assert resolve_manifold_for_offset(-0.24) == "mid_shelf_reach"
    assert resolve_manifold_for_offset(0.15) == "tabletop_stationary_reach"
    assert resolve_manifold_for_offset(-5.0) is None, "an offset outside every envelope must not be forced"


def test_canonical_envelopes_partition_the_height_axis():
    """Canonical envelopes must be disjoint, or classification becomes registry-order dependent."""
    families = {m.embodiment_family for m in KINEMATIC_MANIFOLDS.values() if m.embodiment_family}
    for family in families:
        envelopes = [
            m
            for m in KINEMATIC_MANIFOLDS.values()
            if m.canonical and m.kind == "support_envelope" and m.embodiment_family == family
        ]
        for i, a in enumerate(envelopes):
            for b in envelopes[i + 1 :]:
                disjoint = a.z_max_rel_frame <= b.z_min_rel_frame or b.z_max_rel_frame <= a.z_min_rel_frame
                assert disjoint, f"{a.manifold_id} overlaps {b.manifold_id} for {family}"


def test_registry_shape_is_internally_consistent():
    """Support envelopes need bounds and a family; trajectory labels must not claim either."""
    for manifold in KINEMATIC_MANIFOLDS.values():
        assert manifold.kind in ("support_envelope", "trajectory"), manifold.manifold_id
        if manifold.kind == "support_envelope":
            assert manifold.z_min_rel_frame is not None and manifold.z_max_rel_frame is not None
            assert manifold.z_min_rel_frame < manifold.z_max_rel_frame
            assert manifold.embodiment_family, manifold.manifold_id
        else:
            assert manifold.z_min_rel_frame is None and manifold.z_max_rel_frame is None
        if manifold.alias_of is not None:
            assert not manifold.canonical, f"{manifold.manifold_id} is both an alias and canonical"
            assert manifold.alias_of in KINEMATIC_MANIFOLDS


def test_trajectory_labels_never_classify_as_a_support_envelope():
    """A height query must never return a label that describes motion instead of a surface."""
    for offset in (-0.9, -0.4, 0.0, 0.3):
        resolved = resolve_manifold_for_offset(offset)
        if resolved is not None:
            assert KINEMATIC_MANIFOLDS[resolved].kind == "support_envelope"
            assert KINEMATIC_MANIFOLDS[resolved].canonical


def test_manifold_mismatch_is_reported_as_a_categorical_shift():
    """A scene in a known-but-uncovered envelope gets its own shift; no config patch closes it."""
    # +0.30 from the pelvis is the countertop envelope; the corpus covers only tabletop.
    spec = _relational_spec("maple_table_robolab", nominal_height=0.30)
    shifts = {s.axis: s for s in compute_distribution_shifts(spec, get_policy_profile(GN1X))}

    assert "kinematic_manifold" in shifts
    manifold_shift = shifts["kinematic_manifold"]
    assert not manifold_shift.within_tolerance
    assert manifold_shift.scene_value == "countertop_stationary_reach"
    assert manifold_shift.corpus_value == "tabletop_stationary_reach"
    assert "categorical" in manifold_shift.evidence


def test_offset_outside_every_envelope_implicates_reachability_not_the_policy():
    """Beyond every envelope, the honest reading is "maybe unreachable", not "policy is OOD"."""
    spec = _relational_spec("galileo_locomanip", sector="shelf_tier_3")  # +0.90 from the pelvis
    shifts = {s.axis: s for s in compute_distribution_shifts(spec, get_policy_profile(GN1X))}

    manifold_shift = shifts["kinematic_manifold"]
    assert manifold_shift.scene_value == "outside every registered envelope"
    assert manifold_shift.manifests_as == ("kinematic_unreachable",)
    assert "beyond the arm" in manifold_shift.evidence
    assert manifold_shift.sigma > 1.0, "outside everything should outrank a merely uncovered envelope"


def test_measured_scene_heights_are_close_together():
    """The C1 scenes differ by ~6.5 cm in support height, not the 80 cm the autopsy assumed.

    Measured 2026-09-03 with measure_embodiment_frames.py: galileo apple at +0.0399 from the
    pelvis, maple apple at -0.0251. Both shoulder distances (0.43 m, 0.47 m) sit inside the
    documented 0.35-0.48 m comfortable band. This test pins the correction so the 80 cm figure
    cannot quietly return.
    """
    galileo_offset, maple_offset = 0.0399, -0.0251
    assert abs(galileo_offset - maple_offset) < 0.10

    profile = get_policy_profile(GN1X)
    invariant = profile.invariant("surface_height_rel_pelvis")
    assert invariant.numeric_value == pytest.approx(galileo_offset, abs=0.01)
    # Both scenes fall inside the same reach envelope, so height cannot be the categorical blocker.
    assert resolve_manifold_for_offset(galileo_offset) == resolve_manifold_for_offset(maple_offset)


def test_every_manifold_string_in_generated_specs_is_registered():
    """Free-text manifolds that resolve to nothing are how this abstraction rots."""
    from pathlib import Path

    declared = set()
    for yaml_path in Path("generated_envs").glob("**/*.yaml"):
        for line in yaml_path.read_text(encoding="utf-8").splitlines():
            if "kinematic_manifold:" in line:
                declared.add(line.split(":", 1)[1].strip())
    assert declared, "no kinematic_manifold values found; the scan is not reaching the specs"
    unknown = {m for m in declared if m and m not in KINEMATIC_MANIFOLDS}
    assert not unknown, f"unregistered kinematic_manifold values in generated specs: {sorted(unknown)}"


# ---------------------------------------------------------------------------
# Belief update and planning
# ---------------------------------------------------------------------------


def test_shift_severity_drives_the_dominant_failure_mode():
    profile = get_policy_profile(GN1X)
    state = PolicyDiagnosticState()
    state.seed_from_shifts(compute_distribution_shifts(_tabletop_spec(), profile))

    dominant = state.dominant()
    assert dominant is not None
    # With frames measured, the visual domain is the dominant violated axis -- not height.
    assert dominant[0] == "vision_domain_ood"
    assert state.beliefs["vision_domain_ood"] > FAILURE_MODES["vision_domain_ood"].prior
    # Height is in tolerance, so it must not have been raised at all.
    assert state.beliefs["vertical_reach_ood"] == pytest.approx(
        FAILURE_MODES["vertical_reach_ood"].prior
    )
    # Nothing observed bears on transport dynamics, so that prior must not have moved either.
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

    preserving = select_remediation(state, preserve_target_scene=True)
    assert preserving is not None
    assert preserving[0].preserves_target_scene is True
    # With the visual domain dominant, the scene-preserving fix is to adapt the policy -- which is
    # the direction chosen for this project.
    assert preserving[0].technique_id == "visual_domain_randomization_finetune"

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
    assert "visual_domain" in axes

    # Only blocking shifts assert a violation; in-tolerance axes must not. Height and controller
    # binding are both within tolerance once the frames are measured.
    assert "controller_binding" not in axes
    assert "surface_height_rel_pelvis" not in axes


def test_blocking_shift_query_joins_shifts_to_admissible_remediations():
    profile = get_policy_profile(GN1X)
    spec = _tabletop_spec()
    graph = emit_technique_catalogue_rdf()
    emit_policy_profile_rdf(profile, graph)
    emit_distribution_shifts_rdf(spec.env_name, profile, compute_distribution_shifts(spec, profile), graph)

    rows = query_blocking_shifts(graph)
    assert rows, "SPARQL returned no blocking shifts for an out-of-distribution scene"
    sigmas = [row["sigma"] for row in rows]
    assert sigmas == sorted(sigmas, reverse=True), f"results should be ordered by severity: {sigmas}"
    assert {row["axis"] for row in rows} >= {"visual_domain", "prompt_template"}
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
