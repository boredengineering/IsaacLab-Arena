# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Tests for the corpus embedding bank and its calibrated OOD scores.

The important properties are not "does it return a number" but: does the score separate a shifted
distribution from an unshifted one, does the calibration make the number interpretable, and does
the negative control come back negative. A score that flagged everything, or nothing, would still
produce numbers.
"""

from __future__ import annotations

import pytest

torch = pytest.importorskip("torch")

from isaaclab_arena.agentic_environment_generation.corpus_embedding_bank import (  # noqa: E402
    METRICS,
    CorpusEmbeddingBank,
    auroc,
    build_bank,
    evaluate_separation,
)

DIM = 32
N_REF = 200


def _reference(seed: int = 0, n: int = N_REF) -> torch.Tensor:
    """Anisotropic reference cluster: unequal per-axis scales, so covariance actually matters."""
    generator = torch.Generator().manual_seed(seed)
    scales = torch.linspace(0.2, 2.0, DIM)
    return torch.randn(n, DIM, generator=generator) * scales + 3.0


def _shifted(seed: int = 99, n: int = 40, magnitude: float = 6.0) -> torch.Tensor:
    """A shift with both a directional and a radial component, as a real domain shift would have.

    A purely radial shift (adding a constant to every axis) is invisible to the cosine scores by
    construction; see ``test_cosine_scores_are_blind_to_a_purely_radial_shift``.
    """
    generator = torch.Generator().manual_seed(seed)
    scales = torch.linspace(0.2, 2.0, DIM)
    direction = torch.zeros(DIM)
    direction[: DIM // 2] = magnitude
    direction[DIM // 2 :] = -magnitude
    return torch.randn(n, DIM, generator=generator) * scales + 3.0 + direction


# ---------------------------------------------------------------------------
# Fitting and calibration
# ---------------------------------------------------------------------------


def test_bank_splits_fit_and_heldout_and_calibrates_all_three_metrics():
    bank = build_bank(_reference(), source="unit", heldout_fraction=0.2)

    assert bank.num_fit + bank.num_heldout == N_REF
    assert bank.num_heldout == pytest.approx(0.2 * N_REF, abs=1)
    for metric in METRICS:
        assert len(bank.heldout_scores[metric]) == bank.num_heldout
        assert bank.threshold(metric) is not None
    assert 0.0 <= bank.shrinkage <= 1.0


def test_shrinkage_is_engaged_when_samples_are_scarce_relative_to_dimension():
    """The whole reason for Ledoit-Wolf: a near-singular covariance must not be inverted raw."""
    scarce = build_bank(_reference(n=40), source="scarce")
    plentiful = build_bank(_reference(n=2000), source="plentiful")
    assert scarce.shrinkage > plentiful.shrinkage


def test_scores_are_reproducible_for_a_fixed_split_seed():
    first = build_bank(_reference(), seed=7)
    second = build_bank(_reference(), seed=7)
    probe = _reference(seed=1, n=1)[0]
    assert first.score(probe).knn_cosine == pytest.approx(second.score(probe).knn_cosine)


def test_bank_round_trips_through_disk(tmp_path):
    bank = build_bank(_reference(), source="unit")
    path = bank.save(tmp_path / "bank.pt")
    reloaded = CorpusEmbeddingBank.load(path)

    probe = _shifted(n=1)[0]
    original, restored = bank.score(probe), reloaded.score(probe)
    assert original.mahalanobis == pytest.approx(restored.mahalanobis, rel=1e-5)
    assert original.knn_percentile == restored.knn_percentile
    assert reloaded.summary()["source"] == "unit"


# ---------------------------------------------------------------------------
# Discrimination -- the property that matters
# ---------------------------------------------------------------------------


def test_all_three_scores_separate_a_shifted_distribution():
    bank = build_bank(_reference(), source="unit")
    report = evaluate_separation(bank, _shifted())

    for metric, entry in report["metrics"].items():
        assert entry["auroc"] > 0.9, f"{metric} failed to separate a clearly shifted cluster: {entry}"


def test_negative_control_unseen_reference_data_is_not_flagged():
    """An unseen sample from the SAME distribution must score near the ID range.

    Without this check a score that simply grows with distance from the fit set would look like a
    working OOD detector.
    """
    bank = build_bank(_reference(seed=0), source="unit")
    unseen_same_distribution = _reference(seed=12345, n=40)
    report = evaluate_separation(bank, unseen_same_distribution)

    for metric, entry in report["metrics"].items():
        assert 0.3 < entry["auroc"] < 0.7, f"{metric} flagged in-distribution data as OOD: {entry}"


def test_cosine_scores_are_blind_to_a_purely_radial_shift():
    """A documented limitation, pinned so nobody relies on the cosine scores alone.

    Scaling every embedding outward along the mean direction leaves the angle unchanged, so both
    cosine-based scores see nothing. Mahalanobis and Euclidean kNN both see it. This is exactly the
    "norm removal" weakness that makes cosine-to-centroid the weakest of the family, and it is why
    ``is_ood`` takes the maximum over the calibrated scores rather than trusting one.
    """
    reference = _reference(seed=0, n=400)
    bank = build_bank(reference, source="unit")

    radial = reference[:40] + 8.0  # same direction, larger magnitude
    report = evaluate_separation(bank, radial)

    assert report["metrics"]["cosine_to_centroid"]["auroc"] < 0.7, "cosine should be near-blind here"
    assert report["metrics"]["knn_cosine"]["auroc"] < 0.7, "normalised kNN should be near-blind too"
    assert report["metrics"]["mahalanobis"]["auroc"] > 0.9
    assert report["metrics"]["knn_euclidean"]["auroc"] > 0.9

    # And the combined verdict must still flag it.
    assert bank.score(radial[0]).is_ood() is True


def test_mahalanobis_beats_cosine_on_an_anisotropic_shift():
    """A shift along a low-variance axis is what covariance buys you.

    Cosine-to-centroid discards the norm and assumes an isotropic space, so it should struggle
    where Mahalanobis does not. This is the concrete reason the plan upgraded the score.
    """
    reference = _reference(seed=0, n=400)
    bank = build_bank(reference, source="unit")

    # Perturb only the lowest-variance axis (scale 0.2), by a few of ITS standard deviations.
    shifted = reference[:40].clone()
    shifted[:, 0] += 1.5

    report = evaluate_separation(bank, shifted)
    mahalanobis_auroc = report["metrics"]["mahalanobis"]["auroc"]
    cosine_auroc = report["metrics"]["cosine_to_centroid"]["auroc"]
    assert mahalanobis_auroc > cosine_auroc, (
        f"mahalanobis {mahalanobis_auroc} should beat cosine {cosine_auroc} on a low-variance-axis "
        "shift; that asymmetry is why the covariance is worth computing"
    )


def test_percentile_calibration_makes_the_number_interpretable():
    bank = build_bank(_reference(), source="unit")

    in_distribution = bank.score(_reference(seed=555, n=1)[0])
    out_of_distribution = bank.score(_shifted(n=1)[0])

    assert in_distribution.knn_percentile < 99.0
    assert out_of_distribution.knn_percentile >= 95.0
    assert out_of_distribution.is_ood() is True
    assert in_distribution.is_ood() is False


def test_uncalibrated_bank_refuses_to_answer():
    """Without calibration the OOD question has no answer, and None says so."""
    bank = build_bank(_reference(), source="unit")
    bank.heldout_scores = {}
    scores = bank.score(_shifted(n=1)[0])

    assert scores.knn_percentile is None
    assert scores.is_ood() is None, "an uncalibrated distance must not be turned into a verdict"
    assert scores.mahalanobis > 0.0, "the raw distance is still computed"


# ---------------------------------------------------------------------------
# AUROC helper
# ---------------------------------------------------------------------------


def test_auroc_endpoints_and_ties():
    assert auroc([0.0, 0.1], [1.0, 1.1]) == pytest.approx(1.0)
    assert auroc([1.0, 1.1], [0.0, 0.1]) == pytest.approx(0.0)
    assert auroc([1.0, 1.0], [1.0, 1.0]) == pytest.approx(0.5), "all ties must give exactly chance"
    assert auroc([], [1.0]) != auroc([], [1.0]), "empty input yields NaN, which is not equal to itself"


def test_build_bank_rejects_inputs_it_cannot_calibrate():
    with pytest.raises(AssertionError, match="at least 4"):
        build_bank(torch.randn(2, DIM))
    with pytest.raises(AssertionError, match=r"\(N, D\)"):
        build_bank(torch.randn(10, 4, 4))
