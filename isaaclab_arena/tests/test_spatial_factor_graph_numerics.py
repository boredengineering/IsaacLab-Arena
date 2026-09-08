# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Numerical and result-consistency regressions for spatial relaxation."""

import math
import torch

import pytest

from isaaclab_arena.relations.spatial_factor_graph import SpatialFactorGraph


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_fixed_violations_are_reported_with_formatted_poses(method):
    graph = SpatialFactorGraph()
    graph.add_variable("anchor", [0.0, 0.0, 1.0, math.pi / 2], is_fixed=True)
    graph.add_ground_factor("anchor", weight=2.0, factor_id="ground")
    original = graph.variables["anchor"].mu.clone()

    result = getattr(graph, method)()

    assert not result.converged
    assert result.iterations == 0
    assert result.total_energy == 2.0
    assert result.factor_energies == {"ground": 2.0}
    assert result.conflicting_factors == ["ground"]
    assert result.poses["anchor"] == [0.0, 0.0, 1.0, 90.0]
    assert torch.equal(graph.variables["anchor"].mu, original)


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
@pytest.mark.parametrize("max_iters", [0, 1, 3])
def test_best_snapshot_includes_last_update_and_matching_energies(method, max_iters):
    graph = SpatialFactorGraph()
    graph.add_variable("object", [0.0, 0.0, 1.0])
    graph.add_ground_factor("object", weight=1.0, factor_id="ground")
    kwargs = {"temperature": 0.0} if method == "relax_stochastic" else {}

    result = getattr(graph, method)(max_iters=max_iters, lr=1.5, **kwargs)

    energy, factors = graph.compute_energies()
    assert result.iterations == max_iters
    assert result.factor_energies == factors
    assert result.total_energy == pytest.approx(energy.item())
    assert result.total_energy == pytest.approx(sum(factors.values()))
    assert result.total_energy == pytest.approx(result.poses["object"][2] ** 2, abs=1e-4)
    assert result.conflicting_factors == [fid for fid, value in factors.items() if value > 0.05]
    if max_iters == 0:
        assert result.total_energy == 1.0
    else:
        assert result.total_energy <= 0.25 + 1e-6


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_fixed_only_factors_with_unused_free_variable_need_no_backward(method):
    graph = SpatialFactorGraph()
    graph.add_variable("anchor", [0.0, 0.0, 1.0], is_fixed=True)
    graph.add_variable("unused", [0.0, 0.0, 0.0])
    graph.add_ground_factor("anchor", weight=2.0)

    result = getattr(graph, method)()

    assert result.iterations == 0
    assert result.total_energy == 2.0
    assert not result.converged


def test_stochastic_seed_is_local_reproducible_and_changes_exploration():
    def run(seed):
        graph = SpatialFactorGraph()
        graph.add_variable("object", [0.0, 0.0, 1.0])
        graph.add_ground_factor("object", weight=1.0)
        return graph.relax_stochastic(max_iters=5, temperature=1.0, seed=seed)

    state = torch.random.get_rng_state().clone()
    first = run(17)
    assert torch.equal(state, torch.random.get_rng_state())
    assert first == run(17)
    assert first.poses != run(18).poses
    run(None)
    assert torch.equal(state, torch.random.get_rng_state())


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_relaxation_respects_xy_bounds_without_moving_fixed_nodes(method):
    graph = SpatialFactorGraph()
    graph.add_variable("anchor", [4.0, 0.0, 0.0, math.pi], is_fixed=True, bounds=(-1.0, 1.0, -1.0, 1.0))
    graph.add_variable("object", [0.0, 0.0, 0.0], bounds=(-0.1, 0.1, -0.1, 0.1))
    graph.add_reachability_factor("anchor", "object", target_distance=0.0, tolerance=0.0)
    original = graph.variables["anchor"].mu.clone()

    result = getattr(graph, method)(max_iters=10, lr=0.1)

    assert -0.1 <= result.poses["object"][0] <= 0.1
    assert -0.1 <= result.poses["object"][1] <= 0.1
    assert torch.equal(graph.variables["anchor"].mu, original)
    assert result.poses["anchor"][3] == 180.0


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_initial_free_pose_is_projected_before_evaluation(method):
    graph = SpatialFactorGraph()
    graph.add_variable("object", [2.0, -2.0, 0.0], bounds=(-0.1, 0.1, -0.2, 0.2))
    result = getattr(graph, method)(max_iters=0)
    assert result.poses["object"] == [0.1, -0.2, 0.0, 0.0]


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_iters": -1},
        {"max_iters": 1.5},
        {"max_iters": True},
        {"lr": float("nan")},
        {"lr": float("inf")},
        {"lr": 0.0},
        {"lr": -1.0},
        {"energy_tol": float("nan")},
        {"energy_tol": float("inf")},
        {"energy_tol": -1.0},
    ],
)
def test_invalid_common_optimizer_parameters_are_rejected_even_when_fixed(method, kwargs):
    graph = SpatialFactorGraph()
    graph.add_variable("anchor", [0.0, 0.0, 0.0], is_fixed=True)
    with pytest.raises(AssertionError):
        getattr(graph, method)(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"momentum": float("nan")},
        {"momentum": float("inf")},
        {"momentum": -0.1},
        {"momentum": 1.0},
    ],
)
def test_invalid_adam_momentum_is_rejected(kwargs):
    with pytest.raises(AssertionError):
        SpatialFactorGraph().relax(**kwargs)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"temperature": float("nan")},
        {"temperature": float("inf")},
        {"temperature": -1.0},
        {"cooling_rate": float("nan")},
        {"cooling_rate": float("inf")},
        {"cooling_rate": -0.1},
        {"cooling_rate": 1.1},
        {"seed": 1.5},
        {"seed": True},
        {"seed": -1},
        {"seed": 2**64},
    ],
)
def test_invalid_stochastic_parameters_are_rejected(kwargs):
    with pytest.raises(AssertionError):
        SpatialFactorGraph().relax_stochastic(**kwargs)


@pytest.mark.parametrize("pose", [[0.0, 0.0], [0.0] * 5, [0.0, float("nan"), 0.0], [0.0, 0.0, 1e100]])
def test_invalid_pose_is_rejected(pose):
    with pytest.raises(AssertionError):
        SpatialFactorGraph().add_variable("object", pose)


@pytest.mark.parametrize(
    "bounds", [(1.0, -1.0, 0.0, 1.0), (0.0, 1.0, 1.0, -1.0), (0.0, float("inf"), 0.0, 1.0), (0.0, 1.0)]
)
def test_invalid_xy_bounds_are_rejected(bounds):
    with pytest.raises(AssertionError):
        SpatialFactorGraph().add_variable("object", [0.0, 0.0, 0.0], bounds=bounds)


@pytest.mark.parametrize(
    "method,args,kwargs",
    [
        ("add_ground_factor", ("a",), {"floor_z": float("nan")}),
        ("add_ground_factor", ("a",), {"weight": -1.0}),
        ("add_ground_factor", ("a",), {"weight": float("inf")}),
        ("add_facing_factor", ("a", "b"), {"weight": float("nan")}),
        ("add_clearance_factor", ("a", "b"), {"min_distance": -1.0}),
        ("add_clearance_factor", ("a", "b"), {"weight": -1.0}),
        ("add_reachability_factor", ("a", "b"), {"target_distance": float("inf")}),
        ("add_reachability_factor", ("a", "b"), {"tolerance": -1.0}),
        ("add_reachability_factor", ("a", "b"), {"weight": -1.0}),
        ("add_support_factor", ("a", "b", [-1.0, 1.0, -1.0, 1.0, float("nan")]), {}),
        ("add_support_factor", ("a", "b", [1.0, -1.0, -1.0, 1.0, 0.0]), {}),
        ("add_support_factor", ("a", "b", [-1.0, 1.0, -1.0, 1.0, 0.0]), {"edge_margin": -1.0}),
        ("add_support_factor", ("a", "b", [-1.0, 1.0, -1.0, 1.0, 0.0]), {"edge_margin": 2.0}),
        ("add_support_factor", ("a", "b", [-1.0, 1.0, -1.0, 1.0, 0.0]), {"weight": -1.0}),
        ("add_empirical_reach_likelihood_factor", ("a", "b", [0.0, 0.0, float("inf")]), {}),
        ("add_empirical_reach_likelihood_factor", ("a", "b", [0.0, 0.0, 0.0]), {"sigma": [0.0, 1.0, 1.0]}),
        ("add_empirical_reach_likelihood_factor", ("a", "b", [0.0, 0.0, 0.0]), {"sigma": [-1.0, 1.0, 1.0]}),
        ("add_empirical_reach_likelihood_factor", ("a", "b", [0.0, 0.0, 0.0]), {"sigma": [float("nan"), 1.0, 1.0]}),
        ("add_empirical_reach_likelihood_factor", ("a", "b", [0.0, 0.0, 0.0]), {"weight": -1.0}),
    ],
)
def test_invalid_factor_parameters_are_rejected(method, args, kwargs):
    graph = SpatialFactorGraph()
    graph.add_variable("a", [0.0, 0.0, 0.0, 0.0])
    graph.add_variable("b", [0.0, 0.0, 0.0])
    with pytest.raises(AssertionError):
        getattr(graph, method)(*args, **kwargs)
    assert graph.factors == []


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
@pytest.mark.parametrize("is_fixed", [True, False])
def test_nonfinite_initial_energy_is_rejected(method, is_fixed):
    graph = SpatialFactorGraph()
    graph.add_variable("object", [0.0, 0.0, 1e20], is_fixed=is_fixed)
    graph.add_ground_factor("object")
    with pytest.raises(AssertionError, match="finite"):
        getattr(graph, method)(max_iters=0)


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_overflowing_update_stops_and_restores_finite_best_state(method):
    graph = SpatialFactorGraph()
    graph.add_variable("object", [0.0, 0.0, 1.0])
    graph.add_ground_factor("object", weight=1.0)
    result = getattr(graph, method)(max_iters=3, lr=1e20)
    assert result.iterations == 1
    assert result.total_energy == 1.0
    assert result.poses["object"] == [0.0, 0.0, 1.0, 0.0]
    assert torch.isfinite(graph.variables["object"].mu).all()


@pytest.mark.parametrize("method", ["relax", "relax_stochastic"])
def test_nonfinite_gradient_stops_without_corrupting_poses(method):
    graph = SpatialFactorGraph()
    graph.add_variable("robot", [0.0, 0.0, 0.0], is_fixed=True)
    graph.add_variable("target", [0.0, 0.0, 0.0])
    graph.add_empirical_reach_likelihood_factor(
        "robot", "target", [1e-30, 0.0, 0.0], sigma=[1e-30, 1e-30, 1e-30], weight=1e10
    )
    original = graph.variables["target"].mu.detach().clone()
    result = getattr(graph, method)(max_iters=3)
    assert result.iterations == 0
    assert not result.converged
    assert math.isfinite(result.total_energy)
    assert torch.equal(graph.variables["target"].mu, original)
