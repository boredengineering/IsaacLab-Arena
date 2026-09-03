# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Policy-side knowledge graph: training invariants, failure modes, and the technique catalogue.

The scene graph answers "what did we build". This module answers "can the policy we are about
to evaluate actually operate in it, and if not, what should we measure next". It carries three
closed registries -- failure modes, diagnostic techniques, remediation techniques -- plus the
policy profiles that record what a checkpoint's demonstration corpus held fixed.

Two things make the registries useful rather than decorative:

* ``arena:discriminates`` links each diagnostic technique to the failure modes its evidence can
  separate, so ``select_next_diagnostic`` can pick the cheapest measurement that actually
  reduces uncertainty instead of running the whole battery.
* ``arena:invalidatedBy`` marks remediations that would break a stated invariant, so a fix like
  inflating asset friction is representable, permanently ranked last, and never silently chosen.

Everything here is pure Python and cheap: no torch, no GPU, no simulator. Activation-level
evidence is produced by ``policy_activation_probe`` and fed back in as ``ProbeObservation``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable

# ---------------------------------------------------------------------------
# Value types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class KinematicManifold:
    """A named region of an embodiment's reach space that a corpus may or may not cover.

    Promoted from the free-text ``ReifiedRelationSpec.kinematic_manifold`` field so a corpus can
    declare which manifolds it demonstrates and a scene can be checked against them. A manifold
    mismatch is categorical: no policy-config patch closes it, which is precisely the distinction
    a bare scalar tolerance cannot express.
    """

    manifold_id: str
    description: str
    kind: str
    """``support_envelope`` (where the surface may sit) or ``trajectory`` (how the motion runs).
    Only support envelopes have height bounds; trajectory labels describe the motion instead."""

    embodiment_family: str = ""
    z_min_rel_frame: float | None = None
    """Lower bound of the support height this manifold covers, in the frame named by ``frame``."""

    z_max_rel_frame: float | None = None
    frame: str = "pelvis"
    reach_min_m: float = 0.0
    reach_max_m: float = 0.65
    canonical: bool = True
    """False for a label that names a region an existing canonical envelope already covers. Such
    labels are registered so specs using them still validate, but they are excluded from
    classification so the canonical envelopes remain a partition."""

    alias_of: str | None = None

    def covers_height(self, offset: float) -> bool:
        """Whether a support offset in this manifold's frame falls inside its envelope.

        Half-open on the upper bound so adjacent envelopes classify an offset unambiguously.
        """
        if self.z_min_rel_frame is None or self.z_max_rel_frame is None:
            return False
        return self.z_min_rel_frame <= offset < self.z_max_rel_frame


KINEMATIC_MANIFOLDS: dict[str, KinematicManifold] = {
    m.manifold_id: m
    for m in (
        # --- Canonical G1 support envelopes: a partition of the pelvis-relative height axis. ---
        KinematicManifold(
            manifold_id="low_shelf_reach_down",
            description=(
                "Manipulation on a low deck well below the pelvis, requiring a forward-and-down reach "
                "with torso pitch. The envelope demonstrated by the galileo warehouse-shelf corpus."
            ),
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=-0.95,
            z_max_rel_frame=-0.60,
        ),
        KinematicManifold(
            manifold_id="mid_shelf_reach",
            description="An intermediate deck between the low-shelf and tabletop envelopes.",
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=-0.60,
            z_max_rel_frame=-0.20,
        ),
        KinematicManifold(
            manifold_id="tabletop_stationary_reach",
            description=(
                "Manipulation on a surface near pelvis height, reached forward with little torso pitch."
            ),
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=-0.20,
            z_max_rel_frame=0.20,
        ),
        KinematicManifold(
            manifold_id="countertop_stationary_reach",
            description="Manipulation on a raised counter, above pelvis height.",
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=0.20,
            z_max_rel_frame=0.50,
        ),
        # --- Other embodiment families. ---
        KinematicManifold(
            manifold_id="droid_manipulation_workspace",
            description=(
                "Franka-on-DROID-stand near-field workspace: the tabletop sits well above the arm's "
                "base mount, and the teleoperation corpus only ever placed objects 25-45 cm in front."
            ),
            kind="support_envelope",
            embodiment_family="franka_droid",
            z_min_rel_frame=0.60,
            z_max_rel_frame=0.90,
            frame="base",
            reach_max_m=0.45,
        ),
        # --- Registered aliases: real labels in use that overlap a canonical envelope. ---
        KinematicManifold(
            manifold_id="unitree_g1_bimanual_chest_height",
            description="Bimanual work at chest height; the same region as countertop_stationary_reach.",
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=0.20,
            z_max_rel_frame=0.50,
            canonical=False,
            alias_of="countertop_stationary_reach",
        ),
        KinematicManifold(
            manifold_id="unitree_g1_crouch_manipulation",
            description="Crouching to reach a low deck; the same region as low_shelf_reach_down.",
            kind="support_envelope",
            embodiment_family="unitree_g1",
            z_min_rel_frame=-0.95,
            z_max_rel_frame=-0.60,
            canonical=False,
            alias_of="low_shelf_reach_down",
        ),
        # --- Trajectory labels: describe the motion, not where the surface sits. ---
        KinematicManifold(
            manifold_id="pick_and_place_trajectory",
            description="Grasp, transport, release. Constrains the motion, not the support height.",
            kind="trajectory",
        ),
        KinematicManifold(
            manifold_id="plate_placement_stable",
            description="Release onto a flat receptacle without toppling it.",
            kind="trajectory",
        ),
        KinematicManifold(
            manifold_id="bimanual_transfer_trajectory",
            description="Hand-to-hand transfer between arms.",
            kind="trajectory",
        ),
    )
}
"""The closed set of reach envelopes and trajectory labels.

Height bounds are **provisional** until the Phase 1 sweep measures them -- see
`.agents/references/plans/g1_policy_transfer_implementation_plan.md`. The two non-canonical
entries record that the free-text ``kinematic_manifold`` field accumulated synonyms before it had
a schema; they validate without pretending to partition the axis.
"""


def resolve_manifold_for_offset(offset: float, embodiment_family: str = "unitree_g1") -> str | None:
    """Return the canonical support envelope containing ``offset``, or None when none does.

    Only canonical support envelopes are considered, so the result does not depend on registry
    ordering. Trajectory labels and aliases are excluded by construction.
    """
    for manifold in KINEMATIC_MANIFOLDS.values():
        if (
            manifold.canonical
            and manifold.kind == "support_envelope"
            and manifold.embodiment_family == embodiment_family
            and manifold.covers_height(offset)
        ):
            return manifold.manifold_id
    return None


@dataclass(frozen=True)
class TrainingInvariant:
    """A scene property a demonstration corpus never varied, and so fixed for policies trained on it.

    An invariant may be *attributive* (a lone value on one axis) or **relational** -- constraining
    the offset between two entities related through the scene graph. Relational invariants set
    ``constrains_relation`` and ``relative_to_frame``; the height and lateral invariants are of this
    kind, because reaching is a relative act and only the relation transfers across scenes.
    """

    axis: str
    """Named axis of variation, e.g. ``surface_height_rel_pelvis``."""

    description: str
    unit: str = ""
    value: str | None = None
    """Categorical value, for axes like ``arm_laterality`` or ``prompt_template``."""

    numeric_value: float | None = None
    """Numeric value, for axes like ``surface_height_rel_pelvis``."""

    tolerance: float | None = None
    """Drift on this axis that the policy still tolerates. Shift magnitude is reported in units of it."""

    constrains_relation: str | None = None
    """Relation type this invariant constrains, e.g. ``PLACED_ON``. Set for relational invariants."""

    relative_to_frame: str | None = None
    """Embodiment frame the offset is measured against: ``pelvis``, ``shoulder``, or ``base``."""

    @property
    def is_relational(self) -> bool:
        """Whether this invariant constrains a relation rather than a standalone attribute."""
        return self.constrains_relation is not None


@dataclass(frozen=True)
class PolicyProfile:
    """What a checkpoint is, and what its demonstration corpus assumed."""

    policy_id: str
    checkpoint_uri: str
    policy_kind: str
    """``task_finetuned`` (fitted to one scene) or ``foundation_generalist`` (broadly pretrained)."""

    corpus_id: str
    reference_scene: str
    controller_binding: str
    action_dim: int
    invariants: tuple[TrainingInvariant, ...]
    demo_count: int = 0
    action_chunk_length: int = 16
    vision_backbone: str = ""
    action_head_kind: str = ""
    num_denoising_steps: int = 4
    language_instruction: str = ""
    covered_manifolds: tuple[str, ...] = ()
    """Kinematic manifolds the corpus demonstrates. A scene outside all of them is a categorical
    mismatch, not a tolerance excursion."""

    def invariant(self, axis: str) -> TrainingInvariant | None:
        """Return the invariant on ``axis``, or None if the corpus did not fix that axis."""
        return next((inv for inv in self.invariants if inv.axis == axis), None)


@dataclass(frozen=True)
class FailureMode:
    """A named, attributable cause of evaluation failure."""

    mode_id: str
    label: str
    layer: str
    """Which layer owns the fault: harness, evaluation, perception, conditioning, kinematic,
    dynamics, or training_distribution."""

    prior: float
    description: str
    excludes: tuple[str, ...] = ()
    """Modes that cannot simultaneously be the dominant cause."""


@dataclass(frozen=True)
class DiagnosticTechnique:
    """A procedure that yields evidence separating candidate failure modes."""

    technique_id: str
    label: str
    metric: str
    discriminates: tuple[str, ...]
    cost: float
    """Relative cost in comparable units; selection maximises information gain per unit cost."""

    description: str = ""
    is_activation_probe: bool = False
    probes_module: str | None = None
    requires_policy_weights: bool = False
    """True when the technique needs in-process weights, so it cannot run against a remote server."""

    requires_rollout: bool = False
    requires_gpu: bool = False
    requires_reference_dataset: bool = False

    def is_runnable(self, capabilities: DiagnosticCapabilities) -> bool:
        """Whether the environment currently offers everything this technique needs."""
        return (
            (capabilities.has_policy_weights or not self.requires_policy_weights)
            and (capabilities.has_rollout_artifacts or not self.requires_rollout)
            and (capabilities.has_gpu or not self.requires_gpu)
            and (capabilities.has_reference_dataset or not self.requires_reference_dataset)
        )


@dataclass(frozen=True)
class RemediationTechnique:
    """A procedure that changes the scene, policy config, harness, or training data to fix a failure mode."""

    technique_id: str
    label: str
    resolves: tuple[str, ...]
    expected_efficacy: float
    effort: str
    """``harness``, ``config``, ``layout``, ``data_collection``, or ``training``."""

    cost: float
    description: str = ""
    invalidated_by: tuple[str, ...] = ()
    """Invariants that forbid this remediation. Non-empty means it is never selected by default."""

    preserves_target_scene: bool = True
    """False when the fix works by making the scene resemble the corpus rather than by adapting the
    policy. Such fixes are cheap and effective, but they answer a different question than the one
    the benchmark asked, so a caller committed to the target scene filters them out."""

    patch: dict[str, Any] = field(default_factory=dict)
    """Concrete parameters the remediation engine applies, when the fix is mechanical."""


@dataclass(frozen=True)
class DiagnosticCapabilities:
    """What the caller can actually run right now."""

    has_policy_weights: bool = False
    has_rollout_artifacts: bool = False
    has_gpu: bool = False
    has_reference_dataset: bool = False


@dataclass
class DistributionShift:
    """A measured departure of one environment graph from one training invariant."""

    axis: str
    magnitude: float
    sigma: float
    """Magnitude in units of the invariant's tolerance. ``>= 1.0`` is out of distribution."""

    within_tolerance: bool
    manifests_as: tuple[str, ...]
    evidence: str
    scene_value: str = ""
    corpus_value: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the shift."""
        return {
            "axis": self.axis,
            "magnitude": round(self.magnitude, 4),
            "sigma": round(self.sigma, 3),
            "within_tolerance": self.within_tolerance,
            "manifests_as": list(self.manifests_as),
            "scene_value": self.scene_value,
            "corpus_value": self.corpus_value,
            "evidence": self.evidence,
        }


@dataclass
class ProbeObservation:
    """One measured value retained as evidence for or against failure modes."""

    metric: str
    value: float
    technique_id: str
    supports: tuple[str, ...] = ()
    refutes: tuple[str, ...] = ()
    reference: float | None = None
    likelihood_ratio: float = 3.0
    """P(observation | mode) / P(observation | not mode). Applied to supported modes and inverted for refuted ones."""

    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the observation."""
        return {
            "metric": self.metric,
            "value": self.value,
            "reference": self.reference,
            "technique_id": self.technique_id,
            "supports": list(self.supports),
            "refutes": list(self.refutes),
            "likelihood_ratio": self.likelihood_ratio,
            "note": self.note,
        }


# ---------------------------------------------------------------------------
# Registry: sim-to-real invariants that constrain remediation
# ---------------------------------------------------------------------------

SIM_TO_REAL_INVARIANTS: dict[str, str] = {
    "immutable_material_properties": (
        "Physical material properties of real objects cannot be edited. Raising an asset's USD "
        "friction to force a grasp buys a simulation success that does not transfer, and hides the "
        "controller defect that caused the slip."
    ),
    "fixed_camera_extrinsics": (
        "Head-mounted camera pitch is rigid on physical humanoid hardware. Re-aiming the simulated "
        "camera to centre a target breaks the sim-to-real observation contract."
    ),
    "benchmark_task_specification": (
        "The scenario's stated task -- which object, which arm, which receptacle -- is the thing "
        "being measured. Rewriting it to match a checkpoint's habits reports a different experiment."
    ),
}


# ---------------------------------------------------------------------------
# Registry: failure modes
# ---------------------------------------------------------------------------

FAILURE_MODES: dict[str, FailureMode] = {
    fm.mode_id: fm
    for fm in (
        FailureMode(
            mode_id="harness_false_success",
            label="False-positive success termination",
            layer="evaluation",
            prior=0.04,
            description=(
                "The success predicate fires without the task having been performed, e.g. a contact "
                "sensor triggered by an object nudged against its destination. Recognisable because "
                "the success flag disagrees with the progress objective score."
            ),
        ),
        FailureMode(
            mode_id="spawn_interpenetration",
            label="Spawn-time bounding-box interpenetration",
            layer="harness",
            prior=0.05,
            description=(
                "An object spawns overlapping the robot or a fixture; PhysX de-penetration injects a "
                "large impulse that launches it before the episode starts."
            ),
        ),
        FailureMode(
            mode_id="unsettled_scene",
            label="Scene not settled at inference entry",
            layer="harness",
            prior=0.04,
            description=(
                "Objects still carry velocity when the policy takes its first observation, so the "
                "state it conditions on is not the state it will act in."
            ),
        ),
        FailureMode(
            mode_id="action_space_mismatch",
            label="Action-space or controller-binding mismatch",
            layer="harness",
            prior=0.03,
            description=(
                "The policy's action dimension does not match the embodiment's action backend, or the "
                "backend cannot run the requested number of envs."
            ),
            excludes=("vertical_reach_ood", "vision_domain_ood"),
        ),
        FailureMode(
            mode_id="unconditioned_language",
            label="Empty language conditioning",
            layer="conditioning",
            prior=0.05,
            description=(
                "The policy config carries no language instruction, so the text branch receives an empty string."
            ),
        ),
        FailureMode(
            mode_id="prompt_token_ood",
            label="Instruction outside the corpus prompt distribution",
            layer="conditioning",
            prior=0.07,
            description=(
                "The instruction is well-formed but unlike anything in the demonstration corpus, so "
                "its tokens do not ground onto the learned behaviour."
            ),
        ),
        FailureMode(
            mode_id="vision_domain_ood",
            label="Visual appearance outside the training distribution",
            layer="perception",
            prior=0.12,
            description=(
                "Textures, materials, lighting, or background clutter differ enough from the corpus "
                "that the vision conditioning stops carrying usable signal."
            ),
        ),
        FailureMode(
            mode_id="vision_geometry_ood",
            label="Viewpoint geometry outside the training distribution",
            layer="perception",
            prior=0.10,
            description=(
                "The target projects to a different image region, or the support surface presents a "
                "different depth gradient, than in the corpus -- even when the appearance matches."
            ),
        ),
        FailureMode(
            mode_id="vertical_reach_ood",
            label="Manipulation height outside the training distribution",
            layer="training_distribution",
            prior=0.12,
            description=(
                "The support surface sits at a different height relative to the robot's base than in "
                "every demonstration, so the learned reach prior drives the end effector to the wrong "
                "elevation and stalls against the actual surface."
            ),
        ),
        FailureMode(
            mode_id="arm_laterality_mismatch",
            label="Arm laterality mismatch",
            layer="training_distribution",
            prior=0.06,
            description=(
                "The layout requires the arm the corpus never demonstrated, so the policy reaches with "
                "its trained arm into empty space."
            ),
        ),
        FailureMode(
            mode_id="kinematic_unreachable",
            label="Target outside the reachable workspace",
            layer="kinematic",
            prior=0.08,
            description="The target lies beyond the arm's reach envelope or inside its self-collision volume.",
        ),
        FailureMode(
            mode_id="policy_output_collapse",
            label="Action output collapse",
            layer="conditioning",
            prior=0.08,
            description=(
                "The action head emits near-static or degenerate chunks: the trajectory has almost no "
                "displacement across the horizon regardless of what the observation shows."
            ),
        ),
        FailureMode(
            mode_id="in_flight_slip_inertia",
            label="In-flight slip or inertial drift",
            layer="dynamics",
            prior=0.10,
            description=(
                "Grasping and lifting succeed but transport fails: the object rotates out of the "
                "fingers, or acceleration at chunk boundaries flings it loose."
            ),
        ),
        FailureMode(
            mode_id="horizon_truncation",
            label="Rollout horizon too short",
            layer="evaluation",
            prior=0.06,
            description="The episode ends before a multi-stage task could physically have completed.",
        ),
    )
}


# ---------------------------------------------------------------------------
# Registry: diagnostic techniques
# ---------------------------------------------------------------------------

DIAGNOSTIC_TECHNIQUES: dict[str, DiagnosticTechnique] = {
    dt.technique_id: dt
    for dt in (
        DiagnosticTechnique(
            technique_id="success_progress_consistency_check",
            label="Success-vs-progress consistency check",
            metric="success_progress_disagreement_rate",
            discriminates=("harness_false_success", "horizon_truncation"),
            cost=0.05,
            requires_rollout=True,
            description=(
                "Compares each episode's success flag against its progress objective score. A run that "
                "reports success with a zero progress score, or with an implausibly short episode "
                "length, is measuring the harness rather than the policy."
            ),
        ),
        DiagnosticTechnique(
            technique_id="settle_gate_telemetry",
            label="Phase-1 settle gate telemetry",
            metric="max_object_lin_vel_at_entry",
            discriminates=("unsettled_scene", "spawn_interpenetration"),
            cost=0.1,
            requires_rollout=True,
            description=(
                "Reads per-object linear and angular velocity at inference entry. Large velocities "
                "with objects far from the robot indicate an unpowered-joint collapse; large velocities "
                "on an object near a resting hand indicate spawn interpenetration."
            ),
        ),
        DiagnosticTechnique(
            technique_id="pre_flight_geometry_oracle",
            label="Pre-flight geometric and reachability oracle",
            metric="reach_envelope_violation_count",
            discriminates=("kinematic_unreachable", "spawn_interpenetration", "vision_geometry_ood"),
            cost=0.05,
            description=(
                "Pure-math validation of containment, reach envelope, hand-clearance sectors, and "
                "camera frustum intersection straight from the graph spec, before the simulator starts."
            ),
        ),
        DiagnosticTechnique(
            technique_id="depth_fingerprint_preflight",
            label="Dataset depth-fingerprint pre-flight check",
            metric="predicted_target_uv_delta",
            discriminates=("vision_geometry_ood", "vertical_reach_ood"),
            cost=0.05,
            description=(
                "Projects the target through the known camera model and compares the predicted image "
                "coordinates against a fingerprint measured on the training corpus. No GPU, no rollout."
            ),
        ),
        DiagnosticTechnique(
            technique_id="depth_spatial_audit",
            label="Monocular depth spatial audit",
            metric="surface_pitch_slope_ratio",
            discriminates=("vision_geometry_ood", "vertical_reach_ood", "vision_domain_ood"),
            cost=0.5,
            requires_gpu=True,
            requires_reference_dataset=True,
            description=(
                "Runs monocular depth estimation over a corpus frame and a simulation frame, then "
                "compares surface gradient, target image position, and relative depth."
            ),
        ),
        DiagnosticTechnique(
            technique_id="progress_funnel_statistics",
            label="Markov progress-funnel statistics",
            metric="lift_to_place_conversion_rate",
            discriminates=("in_flight_slip_inertia", "kinematic_unreachable", "horizon_truncation"),
            cost=0.2,
            requires_rollout=True,
            description=(
                "Stage-by-stage completion rates across episodes. A high lift rate with low conversion "
                "localises the fault to transport; a zero lift rate localises it to approach."
            ),
        ),
        DiagnosticTechnique(
            technique_id="wrist_trajectory_tracking",
            label="End-effector trajectory tracking",
            metric="min_wrist_to_target_distance",
            discriminates=("vertical_reach_ood", "arm_laterality_mismatch", "kinematic_unreachable"),
            cost=0.3,
            requires_rollout=True,
            description=(
                "Logs end-effector position against the target through the rollout. Reaching to a "
                "consistent wrong elevation implicates the height prior; reaching to a consistent "
                "wrong side implicates laterality."
            ),
        ),
        DiagnosticTechnique(
            technique_id="vlm_keyframe_autopsy",
            label="Vision-language keyframe autopsy",
            metric="vlm_visibility_score",
            discriminates=("vision_domain_ood", "arm_laterality_mismatch", "kinematic_unreachable"),
            cost=0.6,
            requires_rollout=True,
            description=(
                "Samples keyframes across a rollout and asks a vision-language model for visibility, "
                "layout, and gross kinematic anomalies. Broad but low-precision; best used to generate "
                "hypotheses that a cheaper technique then confirms."
            ),
        ),
        DiagnosticTechnique(
            technique_id="reference_scene_control_run",
            label="Reference-scene control run",
            metric="reference_scene_success_rate",
            discriminates=(
                "action_space_mismatch",
                "vision_domain_ood",
                "vertical_reach_ood",
                "policy_output_collapse",
                "unconditioned_language",
            ),
            cost=0.7,
            requires_rollout=True,
            description=(
                "Evaluates the same checkpoint, server, and controller binding on the scene its corpus "
                "was recorded in. Success there partitions the hypothesis space in one shot: the stack "
                "is sound and the fault is scene divergence. Failure there indicts the stack itself."
            ),
        ),
        DiagnosticTechnique(
            technique_id="action_chunk_dynamics_probe",
            label="Action-chunk dynamics probe",
            metric="chunk_displacement_l2",
            discriminates=("policy_output_collapse", "in_flight_slip_inertia"),
            cost=0.15,
            is_activation_probe=True,
            probes_module="action_head.action_decoder",
            requires_policy_weights=True,
            description=(
                "Measures total predicted displacement across the action horizon and the per-denoising-"
                "step velocity magnitude. A near-zero chunk means the policy is not attempting a "
                "trajectory at all, which is a different fault from attempting a wrong one."
            ),
        ),
        DiagnosticTechnique(
            technique_id="vl_conditioning_delta_probe",
            label="Vision-language conditioning delta probe",
            metric="image_cross_attention_contribution",
            discriminates=("vision_domain_ood", "policy_output_collapse", "unconditioned_language"),
            cost=0.2,
            is_activation_probe=True,
            probes_module="action_head.model.transformer_blocks",
            requires_policy_weights=True,
            description=(
                "Hooks each action-head transformer block and measures the relative hidden-state update "
                "each contributes, bucketed into image cross-attention, text cross-attention, and "
                "self-attention. Image buckets contributing far less than self-attention means the "
                "trajectory is being generated almost without looking."
            ),
        ),
        DiagnosticTechnique(
            technique_id="vision_ablation_sensitivity",
            label="Vision ablation sensitivity",
            metric="action_delta_under_image_ablation",
            discriminates=("vision_domain_ood", "policy_output_collapse"),
            cost=0.25,
            is_activation_probe=True,
            requires_policy_weights=True,
            description=(
                "Runs the same observation twice, once with the camera image replaced by a constant, "
                "and measures how much the predicted action chunk moves. A near-zero delta is causal "
                "evidence that the policy is not conditioning on vision in this state -- the strongest "
                "available separation of 'cannot see' from 'sees but cannot reach'."
            ),
        ),
        DiagnosticTechnique(
            technique_id="vl_embedding_ood_distance",
            label="Vision-language embedding OOD distance",
            metric="cosine_distance_to_corpus_centroid",
            discriminates=("vision_domain_ood", "vision_geometry_ood"),
            cost=0.3,
            is_activation_probe=True,
            probes_module="action_head.vlln",
            requires_policy_weights=True,
            requires_reference_dataset=True,
            description=(
                "Compares the backbone's image-token embeddings for the current observation against a "
                "centroid precomputed over corpus frames. Measures OOD in the representation the action "
                "head actually consumes, rather than in pixel space."
            ),
        ),
        DiagnosticTechnique(
            technique_id="prompt_token_ablation",
            label="Prompt token ablation",
            metric="action_delta_under_prompt_swap",
            discriminates=("prompt_token_ood", "unconditioned_language"),
            cost=0.2,
            is_activation_probe=True,
            requires_policy_weights=True,
            description=(
                "Re-runs inference with the corpus's own instruction in place of the scenario's. A large "
                "action delta means the instruction wording is load-bearing and currently mismatched; a "
                "null delta means the text branch is being ignored either way."
            ),
        ),
    )
}


# ---------------------------------------------------------------------------
# Registry: remediation techniques
# ---------------------------------------------------------------------------

REMEDIATION_TECHNIQUES: dict[str, RemediationTechnique] = {
    rt.technique_id: rt
    for rt in (
        RemediationTechnique(
            technique_id="sequential_success_gate",
            label="Gate placement success behind a verified lift",
            resolves=("harness_false_success",),
            expected_efficacy=0.99,
            effort="harness",
            cost=0.05,
            description=(
                "Evaluate the success predicates as an ordered sequence so contact with the destination "
                "only counts once the object has actually been raised off its resting height."
            ),
            patch={"require_lift_before_place": True, "min_lift_height": 0.05},
        ),
        RemediationTechnique(
            technique_id="clearance_sector_reanchor",
            label="Re-anchor placement sectors clear of the resting hand footprint",
            resolves=("spawn_interpenetration", "kinematic_unreachable"),
            expected_efficacy=0.9,
            effort="layout",
            cost=0.1,
            description=(
                "Offset candidate placement sectors by the robot's resting fingertip reach plus the "
                "object radius, so no spawned body overlaps the embodiment at t=0."
            ),
        ),
        RemediationTechnique(
            technique_id="hold_action_settle_warmup",
            label="Settle with posture-holding actions before inference",
            resolves=("unsettled_scene",),
            expected_efficacy=0.95,
            effort="harness",
            cost=0.05,
            description=(
                "Advance warmup steps through the action manager with a neutral hold action rather than "
                "raw physics steps, so motor torques keep the robot standing while objects settle."
            ),
            patch={"check_settling": True, "settle_steps": 12},
        ),
        RemediationTechnique(
            technique_id="select_matching_controller_binding",
            label="Bind the embodiment backend that matches the policy action space",
            resolves=("action_space_mismatch",),
            expected_efficacy=0.98,
            effort="config",
            cost=0.05,
            description="Choose the embodiment variant whose action dimension equals the checkpoint's output width.",
        ),
        RemediationTechnique(
            technique_id="set_language_instruction",
            label="Populate the policy language instruction",
            resolves=("unconditioned_language",),
            expected_efficacy=0.9,
            effort="config",
            cost=0.05,
        ),
        RemediationTechnique(
            technique_id="align_prompt_to_corpus_template",
            label="Restate the instruction in the corpus's prompt form",
            resolves=("prompt_token_ood",),
            expected_efficacy=0.6,
            effort="config",
            cost=0.05,
            description=(
                "Rephrase the instruction toward the wording the demonstrations were recorded with. "
                "Note that changing which object or arm the instruction names alters the experiment; "
                "that variant is invalidated by the benchmark specification."
            ),
        ),
        RemediationTechnique(
            technique_id="extend_episode_horizon",
            label="Extend the rollout horizon",
            resolves=("horizon_truncation",),
            expected_efficacy=0.85,
            effort="config",
            cost=0.1,
            patch={"num_steps": 2000},
        ),
        RemediationTechnique(
            technique_id="reanchor_surface_to_corpus_height",
            label="Re-anchor the support surface to the corpus manipulation height",
            resolves=("vertical_reach_ood",),
            expected_efficacy=0.85,
            effort="layout",
            cost=0.2,
            description=(
                "Move the support surface, or the robot's standing platform, so the manipulation plane "
                "sits at the height relative to the pelvis that every demonstration used. Preserves the "
                "checkpoint but abandons the scene the benchmark specified."
            ),
            preserves_target_scene=False,
        ),
        RemediationTechnique(
            technique_id="cartesian_vertical_offset_adapter",
            label="Compensate the vertical reach prior in the policy wrapper",
            resolves=("vertical_reach_ood",),
            expected_efficacy=0.35,
            effort="config",
            cost=0.3,
            description=(
                "Add a vertical translation to the policy's end-effector predictions. Tests whether the "
                "learned arm coordination generalises once the height bias is removed, but fights the "
                "closed-loop visual feedback the diffusion head expects, so efficacy is modest."
            ),
        ),
        RemediationTechnique(
            technique_id="mirror_layout_to_corpus_laterality",
            label="Mirror the layout onto the demonstrated arm",
            resolves=("arm_laterality_mismatch",),
            expected_efficacy=0.8,
            effort="layout",
            cost=0.1,
            description=(
                "Reflect the manipuland and receptacle sectors so the reach corridor matches the arm the "
                "corpus demonstrated. Invalidated where the scenario specifies which arm to use."
            ),
            invalidated_by=("benchmark_task_specification",),
            preserves_target_scene=False,
        ),
        RemediationTechnique(
            technique_id="compress_action_chunk",
            label="Compress the action chunk for higher-rate replanning",
            resolves=("in_flight_slip_inertia",),
            expected_efficacy=0.35,
            effort="config",
            cost=0.1,
            description=(
                "Halve the executed chunk length to raise the closed-loop replanning rate. Measured "
                "efficacy is low and the failure mode is bimodal: on one benchmark compressing 16 to 8 "
                "cut conversion from 52% to 16%, so this must be re-measured, never assumed."
            ),
            patch={"action_chunk_length": 8},
        ),
        RemediationTechnique(
            technique_id="increase_denoising_steps",
            label="Increase denoising steps",
            resolves=("in_flight_slip_inertia", "policy_output_collapse"),
            expected_efficacy=0.3,
            effort="config",
            cost=0.15,
            description="Trade inference latency for lower-variance trajectory synthesis.",
        ),
        RemediationTechnique(
            technique_id="binary_gripper_squeeze_bias",
            label="Snap gripper commands to full closure",
            resolves=("in_flight_slip_inertia",),
            expected_efficacy=0.45,
            effort="config",
            cost=0.1,
            description=(
                "Threshold continuous gripper predictions to the fully-closed command to maximise normal force."
            ),
        ),
        RemediationTechnique(
            technique_id="inflate_asset_friction",
            label="Raise asset friction until the grasp holds",
            resolves=("in_flight_slip_inertia",),
            expected_efficacy=0.8,
            effort="config",
            cost=0.05,
            description=(
                "Would work in simulation and is therefore tempting. Retained in the graph precisely so "
                "it is representable and permanently disqualified rather than rediscovered."
            ),
            invalidated_by=("immutable_material_properties",),
        ),
        RemediationTechnique(
            technique_id="visual_domain_randomization_finetune",
            label="Fine-tune with visual domain randomization",
            resolves=("vision_domain_ood", "vision_geometry_ood"),
            expected_efficacy=0.75,
            effort="training",
            cost=3.0,
            description=(
                "Continue training the checkpoint over randomized materials, lighting, and backgrounds "
                "so the vision conditioning stops depending on the corpus's specific appearance. The "
                "transfer-preserving option when the target scene must stay as specified."
            ),
        ),
        RemediationTechnique(
            technique_id="collect_demos_and_finetune",
            label="Collect demonstrations in the target scene and fine-tune",
            resolves=(
                "vision_domain_ood",
                "vision_geometry_ood",
                "vertical_reach_ood",
                "arm_laterality_mismatch",
                "prompt_token_ood",
            ),
            expected_efficacy=0.9,
            effort="data_collection",
            cost=8.0,
            description=(
                "Teleoperate or mimic-generate demonstrations in the target scene and fine-tune. Highest "
                "efficacy and highest cost; the fallback when no cheaper remediation moves the metric."
            ),
        ),
    )
}


# ---------------------------------------------------------------------------
# Registry: policy profiles
# ---------------------------------------------------------------------------

POLICY_PROFILES: dict[str, PolicyProfile] = {
    "GN1x-Tuned-Arena-G1-Static-PickNPlace": PolicyProfile(
        policy_id="GN1x-Tuned-Arena-G1-Static-PickNPlace",
        checkpoint_uri="nvidia/GN1x-Tuned-Arena-G1-Static-PickNPlace",
        policy_kind="task_finetuned",
        corpus_id="Arena-G1-Static-PickNPlace-Task",
        reference_scene="galileo_g1_static_pick_and_place",
        controller_binding="g1_wbc_agile_joint",
        action_dim=50,
        demo_count=200,
        action_chunk_length=40,
        vision_backbone="qwen3_vl",
        action_head_kind="alternate_vl_dit",
        num_denoising_steps=4,
        language_instruction="move the apple to the plate",
        covered_manifolds=("tabletop_stationary_reach",),
        invariants=(
            TrainingInvariant(
                axis="surface_height_rel_pelvis",
                description=(
                    "MEASURED 2026-09-03: the corpus manipuland rests +0.040 m relative to the pelvis, "
                    "i.e. essentially at pelvis height, 0.43 m from the shoulder. This replaces an "
                    "earlier -0.8015 m figure that came from comparing a world-frame shelf z against "
                    "an assumed foot-level base frame; the G1's articulation root is its pelvis, so "
                    "that comparison was off by the assumed 0.75 m offset. The tolerance below is "
                    "still unmeasured -- the Phase 1 sweep exists to determine it."
                ),
                unit="m",
                numeric_value=0.040,
                tolerance=0.15,
                constrains_relation="PLACED_ON",
                relative_to_frame="pelvis",
            ),
            TrainingInvariant(
                axis="arm_laterality",
                description="All demonstrations grasp with the left arm; no right-arm grasp exists in the weights.",
                value="left",
            ),
            TrainingInvariant(
                axis="prompt_template",
                description="The instruction is fixed across the corpus.",
                value="move the apple to the plate",
            ),
            TrainingInvariant(
                axis="visual_domain",
                description=(
                    "Dark matte industrial shelving against dense background clutter under directional "
                    "lighting."
                ),
                value="galileo_locomanip_warehouse_shelf",
            ),
            TrainingInvariant(
                axis="controller_binding",
                description="The 50-D action vector is only valid for the WBC joint backend.",
                value="g1_wbc_agile_joint",
            ),
            TrainingInvariant(
                axis="lateral_offset_rel_base",
                description="The manipuland sits slightly left of the base centreline in every demonstration.",
                unit="m",
                numeric_value=0.199,
                tolerance=0.12,
                constrains_relation="PLACED_ON",
                relative_to_frame="base",
            ),
        ),
    ),
}


def get_policy_profile(policy_ref: str | None) -> PolicyProfile | None:
    """Return the profile whose id or checkpoint URI matches ``policy_ref``.

    Args:
        policy_ref: A profile id, a checkpoint URI, or any string containing one.
    """
    if not policy_ref:
        return None
    for profile in POLICY_PROFILES.values():
        if policy_ref in (profile.policy_id, profile.checkpoint_uri):
            return profile
    return next((p for p in POLICY_PROFILES.values() if p.policy_id in policy_ref), None)


# ---------------------------------------------------------------------------
# Scene-to-corpus shift measurement
# ---------------------------------------------------------------------------

_RECEPTACLE_TOKENS = ("bin", "basket", "box", "tray", "bowl", "plate", "crate", "pot")

# Height of each named embodiment frame above the articulation root, for the Unitree G1.
#
# MEASURED 2026-09-03 with isaaclab_arena_examples/tools/measure_embodiment_frames.py, across both
# the galileo reference scene and the maple-table scene. The G1's articulation root *is* its pelvis
# (``G1SupplementalInfo.root_frame_name == 'pelvis'``), so the pelvis offset is zero -- an earlier
# assumed 0.75 treated the root as a foot-level base frame and inflated every height comparison by
# three quarters of a metre. The shoulder offset reproduced to within 1 mm across both scenes:
#
#   galileo: pelvis z = -0.0445, left_shoulder z = +0.24761  -> +0.2921
#   maple:   pelvis z = +0.09543, left_shoulder z = +0.38653 -> +0.2911
#
# ``spatial_geometric_oracle:423`` still carries the old independent 0.75 for its kinematic-oracle
# warning; that is a separate call site and is wrong for the same reason.
FRAME_HEIGHT_ABOVE_BASE_M: dict[str, float] = {
    "base": 0.0,
    "pelvis": 0.0,
    "shoulder": 0.292,
}


def frame_height(base_pos: list[float], frame: str = "pelvis") -> float:
    """Return the world height of a named embodiment frame for a root at ``base_pos``.

    The G1's articulation root is its pelvis, so a spec's ``initial_pose`` z *is* the pelvis height
    and no ground-anchoring correction applies. Whole-body control settles the pose after reset, so
    the realised height drifts from the declared one by up to ~0.1 m; use
    ``measure_embodiment_frames.py`` when the realised value matters.
    """
    assert frame in FRAME_HEIGHT_ABOVE_BASE_M, f"Unknown embodiment frame {frame!r}"
    return base_pos[2] + FRAME_HEIGHT_ABOVE_BASE_M[frame]


@dataclass(frozen=True)
class SupportRelation:
    """The resolved (embodiment, support surface, manipuland) triple for one scene.

    Produced by traversing the scene graph's relations rather than indexing into object poses,
    because in a generated environment the manipuland usually carries no explicit pose at all --
    the placer derives it from this relation.
    """

    manipuland_id: str
    fixture_id: str | None
    anchor_name: str | None
    surface_z: float | None
    """World z of the support surface, or None when the spec does not determine it."""

    height_source: str
    """How ``surface_z`` was obtained: ``nominal_height``, ``surface_sector``, ``explicit_pose``,
    or ``unresolved``. Recorded because a value inferred from a sector deck is weaker evidence than
    a declared nominal height, and an unresolved one must not be silently treated as zero."""

    lateral_y: float | None = None
    manifold: str | None = None
    """The ``kinematic_manifold`` declared on the corresponding reified relation, if any."""

    frame_z: float | None = None
    """World z of the embodiment frame the offset is measured against."""

    frame: str = "pelvis"

    @property
    def offset_rel_frame(self) -> float | None:
        """Support height minus embodiment frame height, or None when either is unresolved."""
        if self.surface_z is None or self.frame_z is None:
            return None
        return self.surface_z - self.frame_z

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the resolved relation."""
        return {
            "manipuland_id": self.manipuland_id,
            "fixture_id": self.fixture_id,
            "anchor_name": self.anchor_name,
            "surface_z": self.surface_z,
            "height_source": self.height_source,
            "lateral_y": self.lateral_y,
            "manifold": self.manifold,
            "frame": self.frame,
            "frame_z": self.frame_z,
            "offset_rel_frame": self.offset_rel_frame,
        }


def _on_relation_for(spec: Any, subject_id: str) -> Any | None:
    """Return the ``on`` relation whose subject is ``subject_id``, if the spec declares one."""
    for relation in getattr(spec, "relations", []) or []:
        if getattr(relation, "kind", "") == "on" and getattr(relation, "subject", None) == subject_id:
            return relation
    return None


def _reified_relation_for(spec: Any, subject_id: str) -> Any | None:
    """Return the reified PLACED_ON relation whose source is ``subject_id``, if present."""
    for relation in getattr(spec, "reified_relations", None) or []:
        if getattr(relation, "source_id", None) == subject_id and "PLACED_ON" in getattr(
            relation, "relation_type", ""
        ):
            return relation
    return None


def resolve_support_relation(spec: Any, embodiment_frame: str = "pelvis") -> SupportRelation | None:
    """Resolve the support relation for a scene by traversing its relations.

    Height precedence mirrors ``object_placer._sample_on_surface``: an explicit ``nominal_height``
    on the ``on`` relation wins, then a named ``surface_sector``/``surface_anchor`` deck from
    ``FIXTURE_SECTOR_BOUNDS``, then an explicit pose on the manipuland. The source is returned
    alongside the value so a caller can weigh the evidence.

    Args:
        spec: The ``ArenaEnvGraphSpec`` (or any object exposing the same attribute names).
        embodiment_frame: Frame to express the offset against -- ``pelvis``, ``shoulder``, ``base``.

    Returns:
        The resolved relation, or None when the spec declares no manipuland to resolve.
    """
    manipuland, _ = _classify_objects(spec)
    if manipuland is None:
        return None

    embodiment = getattr(spec, "embodiment", None)
    base_pos = _position_of(embodiment) if embodiment is not None else None
    frame_z = frame_height(base_pos, embodiment_frame) if base_pos else None

    on_relation = _on_relation_for(spec, manipuland.id)
    reified = _reified_relation_for(spec, manipuland.id)
    params = (getattr(on_relation, "params", None) or {}) if on_relation is not None else {}

    fixture_id = getattr(on_relation, "reference", None) if on_relation is not None else None
    anchor_name = params.get("surface_sector") or params.get("surface_anchor")
    manifold = getattr(reified, "kinematic_manifold", None) if reified is not None else None

    explicit_pos = _position_of(manipuland)
    surface_z: float | None = None
    height_source = "unresolved"

    if params.get("nominal_height") is not None:
        surface_z = float(params["nominal_height"])
        height_source = "nominal_height"
    elif anchor_name and fixture_id:
        fixture = _fixture_by_id(spec, fixture_id)
        registry_name = getattr(fixture, "registry_name", "") if fixture is not None else ""
        deck_z = _sector_deck_z(registry_name, str(anchor_name))
        if deck_z is not None:
            fixture_pos = _position_of(fixture) if fixture is not None else None
            # The placer adds the fixture's bbox min z; the spec has no bbox, so the fixture's own
            # origin z is the closest available proxy. Recorded as sector-derived accordingly.
            surface_z = deck_z + (fixture_pos[2] if fixture_pos else 0.0)
            height_source = "surface_sector"

    if surface_z is None and explicit_pos is not None:
        surface_z = explicit_pos[2]
        height_source = "explicit_pose"

    return SupportRelation(
        manipuland_id=manipuland.id,
        fixture_id=fixture_id,
        anchor_name=str(anchor_name) if anchor_name else None,
        surface_z=surface_z,
        height_source=height_source,
        lateral_y=(explicit_pos[1] - base_pos[1]) if (explicit_pos and base_pos) else None,
        manifold=manifold,
        frame_z=frame_z,
        frame=embodiment_frame,
    )


def _fixture_by_id(spec: Any, fixture_id: str) -> Any | None:
    """Return the background or object node whose id is ``fixture_id``."""
    background = getattr(spec, "background", None)
    if background is not None and getattr(background, "id", None) == fixture_id:
        return background
    for obj in getattr(spec, "objects", []) or []:
        if obj.id == fixture_id:
            return obj
    return None


def _sector_deck_z(fixture_registry_name: str, sector_name: str) -> float | None:
    """Return the declared deck z for a fixture sector, or None when it is not declared.

    Reads the same ``FIXTURE_SECTOR_BOUNDS`` table the object placer uses, so a sweep that selects
    an anchor by name resolves to the height the simulator will actually place the object at.
    """
    if not fixture_registry_name:
        return None
    try:
        from isaaclab_arena.agentic_environment_generation.spatial_geometric_oracle import (
            FIXTURE_SECTOR_BOUNDS,
        )
    except ImportError:
        return None

    fixture_lower = fixture_registry_name.lower()
    sector_lower = sector_name.lower()
    for fixture_key, sectors in FIXTURE_SECTOR_BOUNDS.items():
        if fixture_key not in fixture_lower:
            continue
        bounds = sectors.get(sector_lower)
        if bounds is None:
            bounds = next(
                (b for key, b in sectors.items() if key in sector_lower or sector_lower in key),
                None,
            )
        if bounds is not None:
            # A declared deck z of exactly 0.0 means "inherit the fixture's own surface", which the
            # spec cannot resolve without a bounding box; report it as undetermined rather than 0.
            return float(bounds[4]) if bounds[4] != 0.0 else None
    return None


def _position_of(asset: Any) -> list[float] | None:
    """Return an asset spec's initial position, or None when it has no explicit pose."""
    params = getattr(asset, "params", None) or {}
    pose = params.get("initial_pose") or {}
    position = pose.get("position_xyz")
    return list(position) if position and len(position) >= 3 else None


def _classify_objects(spec: Any) -> tuple[Any | None, Any | None]:
    """Split a spec's objects into ``(manipuland, receptacle)`` by registry-name tokens."""
    manipuland = None
    receptacle = None
    for obj in getattr(spec, "objects", []) or []:
        name = f"{obj.id} {obj.registry_name}".lower()
        if any(token in name for token in _RECEPTACLE_TOKENS):
            receptacle = receptacle or obj
        else:
            manipuland = manipuland or obj
    return manipuland, receptacle


def compute_distribution_shifts(spec: Any, profile: PolicyProfile) -> list[DistributionShift]:
    """Measure how far an environment graph departs from each of a policy's training invariants.

    This is the scene-graph-to-model-graph bridge: it reads only the declarative spec, so it runs
    before the simulator starts and needs no policy weights.

    Args:
        spec: The ``ArenaEnvGraphSpec`` being evaluated.
        profile: The profile of the policy that will be evaluated in it.

    Returns:
        One shift per invariant the spec carries enough information to measure.
    """
    shifts: list[DistributionShift] = []
    manipuland, _ = _classify_objects(spec)
    embodiment = getattr(spec, "embodiment", None)
    base_pos = _position_of(embodiment) if embodiment else None
    target_pos = _position_of(manipuland) if manipuland else None

    # 1. The support relation: how the manipuland's support surface sits relative to a named frame
    #    on the embodiment. Resolved by graph traversal, since a generated scene's manipuland
    #    usually carries no explicit pose.
    height_inv = profile.invariant("surface_height_rel_pelvis")
    support = resolve_support_relation(spec, height_inv.relative_to_frame or "pelvis") if height_inv else None
    if height_inv and support is not None and height_inv.numeric_value is not None:
        observed = support.offset_rel_frame
        if observed is None:
            # Better to say the spec is under-determined than to invent a height and rank on it.
            shifts.append(
                DistributionShift(
                    axis=height_inv.axis,
                    magnitude=0.0,
                    sigma=0.0,
                    within_tolerance=True,
                    manifests_as=(),
                    scene_value="unresolved",
                    corpus_value=f"{height_inv.numeric_value:+.4f} m",
                    evidence=(
                        f"Support height for '{support.manipuland_id}' could not be resolved from the "
                        f"spec (source={support.height_source}); declare a nominal_height, a known "
                        f"surface_sector, or an explicit pose before this axis can be checked."
                    ),
                )
            )
        else:
            magnitude = observed - height_inv.numeric_value
            tolerance = height_inv.tolerance or 0.1
            sigma = abs(magnitude) / tolerance
            scene_manifold = resolve_manifold_for_offset(observed)
            covered = scene_manifold in profile.covered_manifolds if scene_manifold else False
            manifests = ["vertical_reach_ood", "vision_geometry_ood"] if sigma >= 1.0 else []
            shifts.append(
                DistributionShift(
                    axis=height_inv.axis,
                    magnitude=magnitude,
                    sigma=sigma,
                    within_tolerance=sigma < 1.0,
                    manifests_as=tuple(manifests),
                    scene_value=f"{observed:+.4f} m ({support.height_source})",
                    corpus_value=f"{height_inv.numeric_value:+.4f} m",
                    evidence=(
                        f"Support relation '{support.manipuland_id}' on '{support.fixture_id}'"
                        f"{f' anchor {support.anchor_name}' if support.anchor_name else ''} sits "
                        f"{observed:+.3f} m relative to the {support.frame}; the corpus fixed this at "
                        f"{height_inv.numeric_value:+.3f} m (tolerance {tolerance:.2f} m). "
                        f"Departure {magnitude:+.3f} m = {sigma:.1f}x tolerance. "
                        f"Height source: {support.height_source}. "
                        f"Scene manifold: {scene_manifold or 'outside every registered envelope'}; "
                        f"corpus covers {list(profile.covered_manifolds) or 'nothing declared'}."
                    ),
                )
            )

            # 1b. Manifold coverage is categorical, and worth reporting separately: a scene inside a
            #     manifold the corpus never demonstrated cannot be fixed by a config patch. An
            #     offset outside *every* registered envelope is a stronger signal still, because it
            #     may be beyond the arm entirely -- in which case a failure there says nothing about
            #     the policy.
            if profile.covered_manifolds and not covered:
                outside_all = scene_manifold is None
                shifts.append(
                    DistributionShift(
                        axis="kinematic_manifold",
                        magnitude=1.0,
                        sigma=2.0 if outside_all else 1.0,
                        within_tolerance=False,
                        manifests_as=("vertical_reach_ood",) if not outside_all else ("kinematic_unreachable",),
                        scene_value=scene_manifold or "outside every registered envelope",
                        corpus_value=", ".join(profile.covered_manifolds),
                        evidence=(
                            (
                                f"The support relation sits {observed:+.3f} m from the "
                                f"{support.frame}, outside every registered reach envelope. This may "
                                f"be beyond the arm rather than merely out of distribution -- verify "
                                f"reachability before attributing a failure here to the policy."
                            )
                            if outside_all
                            else (
                                f"The support relation instantiates the '{scene_manifold}' reach "
                                f"envelope, which this corpus does not cover (it demonstrates "
                                f"{', '.join(profile.covered_manifolds)}). A manifold mismatch is "
                                f"categorical: no policy-config change closes it, only re-relating "
                                f"the scene or extending the training distribution."
                            )
                        ),
                    )
                )

    # 2. Lateral offset, which also determines which arm the reach corridor demands.
    lateral_inv = profile.invariant("lateral_offset_rel_base")
    if lateral_inv and base_pos and target_pos and lateral_inv.numeric_value is not None:
        observed = target_pos[1] - base_pos[1]
        magnitude = observed - lateral_inv.numeric_value
        tolerance = lateral_inv.tolerance or 0.1
        sigma = abs(magnitude) / tolerance
        shifts.append(
            DistributionShift(
                axis=lateral_inv.axis,
                magnitude=magnitude,
                sigma=sigma,
                within_tolerance=sigma < 1.0,
                manifests_as=("arm_laterality_mismatch", "kinematic_unreachable"),
                scene_value=f"{observed:+.4f} m",
                corpus_value=f"{lateral_inv.numeric_value:+.4f} m",
                evidence=(
                    f"Manipuland sits {observed:+.3f} m laterally from the base centreline; the corpus "
                    f"fixed this at {lateral_inv.numeric_value:+.3f} m. Departure {magnitude:+.3f} m = "
                    f"{sigma:.1f}x tolerance."
                ),
            )
        )

    # 3. Arm laterality, inferred from which side of the base the manipuland sits on.
    arm_inv = profile.invariant("arm_laterality")
    if arm_inv and base_pos and target_pos:
        observed_side = "left" if (target_pos[1] - base_pos[1]) >= 0.0 else "right"
        mismatch = observed_side != (arm_inv.value or observed_side)
        shifts.append(
            DistributionShift(
                axis=arm_inv.axis,
                magnitude=1.0 if mismatch else 0.0,
                sigma=1.0 if mismatch else 0.0,
                within_tolerance=not mismatch,
                manifests_as=("arm_laterality_mismatch",),
                scene_value=observed_side,
                corpus_value=arm_inv.value or "",
                evidence=(
                    f"Layout places the manipuland on the {observed_side}; the corpus demonstrates only "
                    f"{arm_inv.value} arm grasps."
                    if mismatch
                    else f"Layout laterality matches the demonstrated {arm_inv.value} arm."
                ),
            )
        )

    # 4. Prompt wording.
    prompt_inv = profile.invariant("prompt_template")
    task = getattr(spec, "task", None)
    description = (getattr(task, "description", None) or "").strip()
    if prompt_inv and prompt_inv.value is not None:
        mismatch = description.lower() != prompt_inv.value.lower()
        shifts.append(
            DistributionShift(
                axis=prompt_inv.axis,
                magnitude=1.0 if mismatch else 0.0,
                sigma=1.0 if mismatch else 0.0,
                within_tolerance=not mismatch,
                manifests_as=("prompt_token_ood",) if description else ("unconditioned_language",),
                scene_value=description or "<empty>",
                corpus_value=prompt_inv.value,
                evidence=(
                    f"Task instruction {description!r} differs from the corpus instruction "
                    f"{prompt_inv.value!r}."
                    if mismatch
                    else "Task instruction matches the corpus instruction verbatim."
                ),
            )
        )

    # 5. Visual domain, approximated by the background asset identity.
    visual_inv = profile.invariant("visual_domain")
    background = getattr(spec, "background", None)
    if visual_inv and background is not None:
        observed = getattr(background, "registry_name", "") or ""
        mismatch = profile.reference_scene not in observed and observed not in (visual_inv.value or "")
        shifts.append(
            DistributionShift(
                axis=visual_inv.axis,
                magnitude=1.0 if mismatch else 0.0,
                sigma=1.0 if mismatch else 0.0,
                within_tolerance=not mismatch,
                manifests_as=("vision_domain_ood",),
                scene_value=observed,
                corpus_value=visual_inv.value or "",
                evidence=(
                    f"Background asset {observed!r} is not the corpus scene {visual_inv.value!r}; every "
                    f"demonstration frame shows the latter."
                    if mismatch
                    else f"Background matches the corpus scene {observed!r}."
                ),
            )
        )

    # 6. Controller binding.
    binding_inv = profile.invariant("controller_binding")
    if binding_inv and embodiment is not None and binding_inv.value:
        observed = getattr(embodiment, "registry_name", "") or ""
        mismatch = binding_inv.value not in observed
        shifts.append(
            DistributionShift(
                axis=binding_inv.axis,
                magnitude=1.0 if mismatch else 0.0,
                sigma=1.0 if mismatch else 0.0,
                within_tolerance=not mismatch,
                manifests_as=("action_space_mismatch",),
                scene_value=observed,
                corpus_value=binding_inv.value,
                evidence=(
                    f"Embodiment {observed!r} does not provide the {binding_inv.value!r} backend the "
                    f"checkpoint's {profile.action_dim}-D action vector requires."
                    if mismatch
                    else f"Embodiment provides the required {binding_inv.value!r} backend."
                ),
            )
        )

    return shifts


# ---------------------------------------------------------------------------
# Belief state and the technique planner
# ---------------------------------------------------------------------------


@dataclass
class PolicyDiagnosticState:
    """Belief over failure modes, updated by distribution shifts and probe observations."""

    beliefs: dict[str, float] = field(default_factory=dict)
    applied_techniques: list[str] = field(default_factory=list)
    observations: list[ProbeObservation] = field(default_factory=list)
    shifts: list[DistributionShift] = field(default_factory=list)

    def __post_init__(self):
        if not self.beliefs:
            self.beliefs = {mode_id: mode.prior for mode_id, mode in FAILURE_MODES.items()}

    def seed_from_shifts(self, shifts: Iterable[DistributionShift]) -> None:
        """Raise belief in the failure modes that out-of-tolerance shifts are expected to produce.

        A shift's severity in units of its own tolerance becomes the odds multiplier, so a small
        drift nudges belief while a multi-tolerance departure dominates the posterior.
        """
        for shift in shifts:
            self.shifts.append(shift)
            if shift.within_tolerance:
                continue
            multiplier = 1.0 + min(shift.sigma, 8.0)
            for mode_id in shift.manifests_as:
                if mode_id in self.beliefs:
                    self.beliefs[mode_id] = _bayes_update(self.beliefs[mode_id], multiplier)
        self._apply_exclusions()

    def apply_observations(self, observations: Iterable[ProbeObservation]) -> None:
        """Fold probe evidence into the belief state."""
        for observation in observations:
            self.observations.append(observation)
            if observation.technique_id not in self.applied_techniques:
                self.applied_techniques.append(observation.technique_id)
            ratio = max(observation.likelihood_ratio, 1e-3)
            for mode_id in observation.supports:
                if mode_id in self.beliefs:
                    self.beliefs[mode_id] = _bayes_update(self.beliefs[mode_id], ratio)
            for mode_id in observation.refutes:
                if mode_id in self.beliefs:
                    self.beliefs[mode_id] = _bayes_update(self.beliefs[mode_id], 1.0 / ratio)
        self._apply_exclusions()

    def _apply_exclusions(self) -> None:
        """Damp modes excluded by a strictly more probable competing mode."""
        for mode_id, mode in FAILURE_MODES.items():
            for excluded_id in mode.excludes:
                if excluded_id in self.beliefs and self.beliefs.get(mode_id, 0.0) > self.beliefs[excluded_id]:
                    self.beliefs[excluded_id] *= 0.5

    def ranked(self, min_belief: float = 0.0) -> list[tuple[str, float]]:
        """Return ``(mode_id, belief)`` sorted most probable first."""
        ranked = sorted(self.beliefs.items(), key=lambda kv: kv[1], reverse=True)
        return [(mode_id, belief) for mode_id, belief in ranked if belief >= min_belief]

    def dominant(self) -> tuple[str, float] | None:
        """Return the most probable failure mode, or None when the belief state is empty."""
        ranked = self.ranked()
        return ranked[0] if ranked else None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view of the belief state."""
        return {
            "beliefs": {mode_id: round(belief, 4) for mode_id, belief in self.ranked()},
            "applied_techniques": list(self.applied_techniques),
            "shifts": [shift.to_dict() for shift in self.shifts],
            "observations": [observation.to_dict() for observation in self.observations],
        }


def _bayes_update(prior: float, likelihood_ratio: float) -> float:
    """Update ``prior`` by ``likelihood_ratio`` in odds space, clamped away from 0 and 1."""
    prior = min(max(prior, 1e-4), 1.0 - 1e-4)
    odds = prior / (1.0 - prior) * likelihood_ratio
    return min(max(odds / (1.0 + odds), 1e-4), 1.0 - 1e-4)


def _binary_entropy(probability: float) -> float:
    """Shannon entropy in bits of a Bernoulli variable."""
    probability = min(max(probability, 1e-9), 1.0 - 1e-9)
    return -(probability * math.log2(probability) + (1 - probability) * math.log2(1 - probability))


def expected_information_gain(technique: DiagnosticTechnique, state: PolicyDiagnosticState) -> float:
    """Bits of uncertainty the technique could remove, summed over the modes it discriminates.

    A technique is worth running in proportion to how undecided the modes it separates currently
    are: it earns nothing for confirming a mode already believed, or dismissing one already ruled
    out.
    """
    return sum(
        _binary_entropy(state.beliefs[mode_id]) for mode_id in technique.discriminates if mode_id in state.beliefs
    )


def select_next_diagnostic(
    state: PolicyDiagnosticState,
    capabilities: DiagnosticCapabilities,
    exclude_applied: bool = True,
) -> tuple[DiagnosticTechnique, float] | None:
    """Choose the runnable diagnostic technique with the best information gain per unit cost.

    Args:
        state: Current belief over failure modes.
        capabilities: What can actually be run right now.
        exclude_applied: Skip techniques already recorded in ``state.applied_techniques``.

    Returns:
        ``(technique, score)`` for the best candidate, or None when nothing runnable remains.
    """
    best: tuple[DiagnosticTechnique, float] | None = None
    for technique in DIAGNOSTIC_TECHNIQUES.values():
        if exclude_applied and technique.technique_id in state.applied_techniques:
            continue
        if not technique.is_runnable(capabilities):
            continue
        gain = expected_information_gain(technique, state)
        if gain <= 0.0:
            continue
        score = gain / max(technique.cost, 1e-3)
        if best is None or score > best[1]:
            best = (technique, score)
    return best


def plan_diagnostic_sequence(
    state: PolicyDiagnosticState,
    capabilities: DiagnosticCapabilities,
    max_techniques: int = 4,
) -> list[DiagnosticTechnique]:
    """Return the technique order the planner would follow, without executing anything.

    Each step assumes the previous technique resolved the modes it discriminates, which is what
    makes the sequence spread across the hypothesis space instead of repeatedly re-measuring the
    same axis.
    """
    probe_state = PolicyDiagnosticState(
        beliefs=dict(state.beliefs),
        applied_techniques=list(state.applied_techniques),
    )
    plan: list[DiagnosticTechnique] = []
    for _ in range(max_techniques):
        selection = select_next_diagnostic(probe_state, capabilities)
        if selection is None:
            break
        technique, _score = selection
        plan.append(technique)
        probe_state.applied_techniques.append(technique.technique_id)
        # Assume the measurement lands decisively, so the next pick targets untouched uncertainty.
        for mode_id in technique.discriminates:
            if mode_id in probe_state.beliefs:
                probe_state.beliefs[mode_id] = 0.98 if probe_state.beliefs[mode_id] >= 0.5 else 0.02
    return plan


def select_remediation(
    state: PolicyDiagnosticState,
    allow_invalidated: bool = False,
    max_effort: str | None = None,
    require_dominant: bool = True,
    preserve_target_scene: bool = False,
) -> tuple[RemediationTechnique, float] | None:
    """Choose the remediation with the best belief-weighted efficacy per unit cost.

    Args:
        state: Current belief over failure modes.
        allow_invalidated: Include remediations that break a stated invariant. Off by default;
            turning it on is a deliberate, recorded choice rather than an optimisation.
        max_effort: Cap the effort tier considered, e.g. ``config`` to exclude retraining.
        require_dominant: Only consider remediations that address the most probable failure mode.
            Without this, cost normalisation lets a cheap fix for a minor mode outrank the only
            fix for the actual cause.
        preserve_target_scene: Exclude remediations that work by making the scene resemble the
            training corpus. Set this when the scene is the thing being evaluated and the policy
            is what may change.

    Returns:
        ``(technique, score)`` for the best candidate, or None when nothing admissible applies.
    """
    effort_order = ["harness", "config", "layout", "data_collection", "training"]
    effort_ceiling = effort_order.index(max_effort) if max_effort in effort_order else len(effort_order) - 1
    dominant = state.dominant()
    dominant_mode = dominant[0] if dominant and require_dominant else None

    best: tuple[RemediationTechnique, float] | None = None
    for technique in REMEDIATION_TECHNIQUES.values():
        if technique.invalidated_by and not allow_invalidated:
            continue
        if preserve_target_scene and not technique.preserves_target_scene:
            continue
        if technique.effort in effort_order and effort_order.index(technique.effort) > effort_ceiling:
            continue
        if dominant_mode is not None and dominant_mode not in technique.resolves:
            continue
        weighted = sum(state.beliefs.get(mode_id, 0.0) for mode_id in technique.resolves)
        if weighted <= 0.0:
            continue
        score = weighted * technique.expected_efficacy / max(technique.cost, 1e-3)
        if best is None or score > best[1]:
            best = (technique, score)
    return best


def rank_remediations(
    state: PolicyDiagnosticState,
    allow_invalidated: bool = False,
    max_effort: str | None = None,
    require_dominant: bool = True,
    preserve_target_scene: bool = False,
) -> list[tuple[RemediationTechnique, float]]:
    """Return every admissible remediation, best score first.

    ``select_remediation`` returns only the argmax, which hides an important distinction: a cheap
    low-efficacy fix can outrank an expensive high-efficacy one on cost-normalised score even when
    the shift driving the failure is far beyond anything a config change can absorb. Callers
    deciding how much effort to spend should read the ranking, not just its head.
    """
    effort_order = ["harness", "config", "layout", "data_collection", "training"]
    effort_ceiling = effort_order.index(max_effort) if max_effort in effort_order else len(effort_order) - 1
    dominant = state.dominant()
    dominant_mode = dominant[0] if dominant and require_dominant else None

    ranked: list[tuple[RemediationTechnique, float]] = []
    for technique in REMEDIATION_TECHNIQUES.values():
        if technique.invalidated_by and not allow_invalidated:
            continue
        if preserve_target_scene and not technique.preserves_target_scene:
            continue
        if technique.effort in effort_order and effort_order.index(technique.effort) > effort_ceiling:
            continue
        if dominant_mode is not None and dominant_mode not in technique.resolves:
            continue
        weighted = sum(state.beliefs.get(mode_id, 0.0) for mode_id in technique.resolves)
        if weighted <= 0.0:
            continue
        ranked.append((technique, weighted * technique.expected_efficacy / max(technique.cost, 1e-3)))
    return sorted(ranked, key=lambda pair: pair[1], reverse=True)


def diagnose_transfer_readiness(
    spec: Any,
    policy_ref: str,
    capabilities: DiagnosticCapabilities | None = None,
    preserve_target_scene: bool = False,
) -> dict[str, Any]:
    """Assess, before any rollout, whether a policy can be expected to operate in a scene.

    Measures the scene against the policy's training invariants, seeds a belief state from the
    out-of-tolerance shifts, and reports the diagnostic sequence and remediation the planner would
    choose next.

    Args:
        spec: The ``ArenaEnvGraphSpec`` to assess.
        policy_ref: Profile id or checkpoint URI of the policy to be evaluated.
        capabilities: What can be run; defaults to spec-only (no rollout, no weights, no GPU).
        preserve_target_scene: Treat the scene as fixed, so only remediations that adapt the policy
            are recommended. The report always includes both options for comparison.

    Returns:
        A report with the measured shifts, seeded beliefs, planned techniques, and recommended
        remediation. ``profile_known`` is False when the policy has no registered profile, in which
        case no invariants could be checked.
    """
    profile = get_policy_profile(policy_ref)
    if profile is None:
        return {
            "profile_known": False,
            "policy_ref": policy_ref,
            "message": (
                f"No policy profile registered for {policy_ref!r}; transfer readiness cannot be assessed "
                f"until its demonstration corpus invariants are declared in POLICY_PROFILES."
            ),
        }

    capabilities = capabilities or DiagnosticCapabilities()
    shifts = compute_distribution_shifts(spec, profile)
    state = PolicyDiagnosticState()
    state.seed_from_shifts(shifts)

    plan = plan_diagnostic_sequence(state, capabilities)
    remediation = select_remediation(state, preserve_target_scene=preserve_target_scene)
    scene_preserving = select_remediation(state, preserve_target_scene=True)
    scene_changing = select_remediation(state, preserve_target_scene=False)
    out_of_tolerance = [shift for shift in shifts if not shift.within_tolerance]
    dominant = state.dominant()

    return {
        "profile_known": True,
        "policy_ref": profile.policy_id,
        "policy_kind": profile.policy_kind,
        "reference_scene": profile.reference_scene,
        "transfer_expected": not out_of_tolerance,
        "shifts": [shift.to_dict() for shift in shifts],
        "out_of_tolerance_axes": [shift.axis for shift in out_of_tolerance],
        "worst_shift_sigma": round(max((s.sigma for s in shifts), default=0.0), 3),
        "beliefs": {mode_id: round(belief, 4) for mode_id, belief in state.ranked(min_belief=0.05)},
        "dominant_failure_mode": dominant[0] if dominant else None,
        "planned_diagnostics": [technique.technique_id for technique in plan],
        "recommended_remediation": remediation[0].technique_id if remediation else None,
        "recommended_remediation_patch": dict(remediation[0].patch) if remediation else {},
        # Both branches are reported because the choice between adapting the policy and adapting
        # the scene is a decision about what the benchmark is measuring, not an optimisation.
        "scene_preserving_remediation": scene_preserving[0].technique_id if scene_preserving else None,
        "scene_changing_remediation": scene_changing[0].technique_id if scene_changing else None,
        "remediation_ranking": [
            {
                "technique_id": technique.technique_id,
                "effort": technique.effort,
                "expected_efficacy": technique.expected_efficacy,
                "cost": technique.cost,
                "preserves_target_scene": technique.preserves_target_scene,
                "score": round(score, 4),
            }
            for technique, score in rank_remediations(state, preserve_target_scene=preserve_target_scene)
        ],
    }
