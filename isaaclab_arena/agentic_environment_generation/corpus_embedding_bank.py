# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""A reference bank of corpus image-token embeddings, and calibrated OOD scores against it.

The question is whether the frozen vision backbone represents a target scene differently from the
scenes the policy was trained on. That is an out-of-distribution test in the representation the
action head actually consumes, which is strictly more relevant than a pixel-space or depth-space
comparison.

Three scores are computed rather than one, because the OOD literature does not name a universal
winner and the ordering flips by dataset:

* ``cosine_to_centroid`` -- cheap, and the metric this project registered first. It is Mahalanobis
  with an identity covariance and the vector norm discarded, which makes it the weakest of the
  three in general. It stays competitive here because in *transformer* embedding spaces angular and
  Mahalanobis scores nearly coincide.
* ``mahalanobis`` -- accounts for the covariance of the reference distribution. Nearly free: one
  pass, no index. Uses Ledoit-Wolf shrinkage because D=2048 against a few thousand samples makes
  the raw empirical covariance badly conditioned.
* ``knn_cosine`` -- cosine distance to the k-th nearest L2-normalised reference embedding. Makes no
  distributional assumption and is generally the strongest, at the cost of retaining the bank.
* ``knn_euclidean`` -- the same, without L2 normalisation.

That last score exists because of a limitation worth stating plainly: **both cosine scores are
blind to a shift along the mean direction.** Normalising away the vector norm is what makes them
robust to brightness-like scaling, and it is also what makes them unable to see a distribution that
moved radially outward. A unit test pins this behaviour. If a domain shift manifests partly as a
change in embedding magnitude -- which cannot be ruled out for image tokens -- only the Mahalanobis
and Euclidean-kNN scores will register it, so all four are always reported together.

**A raw distance is not a result.** Any of these numbers is uninterpretable on its own, so the bank
holds a held-out slice of reference embeddings and every score is reported as a percentile against
that in-distribution distribution, plus an AUROC for separating held-out reference frames from
target frames. This replaces an a-priori threshold with a measured one.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Fraction of reference embeddings held out to calibrate the in-distribution score distribution.
HELDOUT_FRACTION = 0.2
# Neighbour count for the kNN score. k=3 is the usual default for image backbones.
KNN_K = 3
# Percentile of the in-distribution scores above which an observation is called OOD. Replaces the
# hardcoded threshold it supersedes.
OOD_PERCENTILE = 95.0

METRICS = ("cosine_to_centroid", "mahalanobis", "knn_cosine", "knn_euclidean")
"""Every score is reported for every observation; none is trusted alone."""


@dataclass
class OODScores:
    """The three scores for one observation, with percentiles against the reference distribution."""

    cosine_to_centroid: float
    mahalanobis: float
    knn_cosine: float
    knn_euclidean: float
    cosine_percentile: float | None = None
    mahalanobis_percentile: float | None = None
    knn_percentile: float | None = None
    knn_euclidean_percentile: float | None = None

    def is_ood(self, percentile: float = OOD_PERCENTILE) -> bool | None:
        """Whether the strongest available score exceeds the calibrated percentile.

        Returns None when the bank carried no calibration, because an uncalibrated distance cannot
        support the claim.
        """
        if self.knn_percentile is None:
            return None
        # The maximum over the calibrated scores: a shift visible to any one of them is a shift.
        # Taking only the cosine kNN would miss purely radial displacement by construction.
        available = [
            p
            for p in (self.knn_percentile, self.knn_euclidean_percentile, self.mahalanobis_percentile)
            if p is not None
        ]
        return max(available) >= percentile

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable view."""
        return {
            "cosine_to_centroid": round(self.cosine_to_centroid, 6),
            "mahalanobis": round(self.mahalanobis, 6),
            "knn_cosine": round(self.knn_cosine, 6),
            "knn_euclidean": round(self.knn_euclidean, 6),
            "cosine_percentile": self.cosine_percentile,
            "mahalanobis_percentile": self.mahalanobis_percentile,
            "knn_percentile": self.knn_percentile,
            "knn_euclidean_percentile": self.knn_euclidean_percentile,
        }


@dataclass
class CorpusEmbeddingBank:
    """Reference embeddings plus the statistics needed to score a new observation against them."""

    mean: Any
    """(D,) mean of the fitted reference embeddings."""

    precision: Any
    """(D, D) inverse of the shrunk covariance."""

    normalized_bank: Any
    """(N_fit, D) L2-normalised reference embeddings, for the cosine kNN score."""

    raw_bank: Any = None
    """(N_fit, D) un-normalised reference embeddings, for the Euclidean kNN score."""

    heldout_scores: dict[str, list[float]] = field(default_factory=dict)
    """In-distribution score distributions from the held-out slice, for percentile calibration."""

    source: str = ""
    num_fit: int = 0
    num_heldout: int = 0
    shrinkage: float = 0.0

    def score(self, embedding: Any) -> OODScores:
        """Score one pooled image-token embedding against the bank."""
        import torch

        vector = embedding.detach().float().flatten()
        centered = (vector - self.mean).unsqueeze(0)

        cosine = 1.0 - float(
            torch.nn.functional.cosine_similarity(vector.unsqueeze(0), self.mean.unsqueeze(0)).squeeze()
        )
        mahalanobis = float(torch.sqrt(torch.clamp(centered @ self.precision @ centered.T, min=0.0)).squeeze())

        normalized = torch.nn.functional.normalize(vector, dim=0)
        similarities = self.normalized_bank @ normalized
        k = min(KNN_K, similarities.numel())
        knn = 1.0 - float(torch.topk(similarities, k).values[-1])

        if self.raw_bank is not None:
            distances = torch.linalg.vector_norm(self.raw_bank - vector.unsqueeze(0), dim=1)
            knn_euclidean = float(torch.topk(distances, k, largest=False).values[-1])
        else:
            knn_euclidean = float("nan")

        scores = OODScores(
            cosine_to_centroid=cosine,
            mahalanobis=mahalanobis,
            knn_cosine=knn,
            knn_euclidean=knn_euclidean,
        )
        scores.cosine_percentile = self._percentile("cosine_to_centroid", cosine)
        scores.mahalanobis_percentile = self._percentile("mahalanobis", mahalanobis)
        scores.knn_percentile = self._percentile("knn_cosine", knn)
        scores.knn_euclidean_percentile = self._percentile("knn_euclidean", knn_euclidean)
        return scores

    def _percentile(self, metric: str, value: float) -> float | None:
        """Return ``value``'s percentile within the held-out in-distribution scores."""
        reference = self.heldout_scores.get(metric)
        if not reference:
            return None
        below = sum(1 for r in reference if r <= value)
        return round(100.0 * below / len(reference), 3)

    def threshold(self, metric: str = "knn_cosine", percentile: float = OOD_PERCENTILE) -> float | None:
        """Return the measured in-distribution score at ``percentile``."""
        reference = sorted(self.heldout_scores.get(metric, []))
        if not reference:
            return None
        index = min(len(reference) - 1, int(round(percentile / 100.0 * (len(reference) - 1))))
        return reference[index]

    def save(self, path: Path | str) -> Path:
        """Persist the bank to a ``.pt`` file."""
        import torch

        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save(
            {
                "mean": self.mean,
                "precision": self.precision,
                "normalized_bank": self.normalized_bank,
                "raw_bank": self.raw_bank,
                "heldout_scores": self.heldout_scores,
                "source": self.source,
                "num_fit": self.num_fit,
                "num_heldout": self.num_heldout,
                "shrinkage": self.shrinkage,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: Path | str) -> CorpusEmbeddingBank:
        """Load a bank previously written by ``save``."""
        import torch

        payload = torch.load(Path(path), map_location="cpu", weights_only=False)
        return cls(**payload)

    def summary(self) -> dict[str, Any]:
        """Return a JSON-serializable description of the fitted bank."""
        return {
            "source": self.source,
            "num_fit": self.num_fit,
            "num_heldout": self.num_heldout,
            "shrinkage": round(self.shrinkage, 6),
            "dimension": int(self.mean.shape[0]),
            "thresholds_at_p95": {metric: self.threshold(metric) for metric in METRICS},
        }


def _ledoit_wolf_shrinkage(centered: Any) -> tuple[Any, float]:
    """Return a shrunk covariance and the shrinkage coefficient.

    With D=2048 and only a few thousand samples the empirical covariance is near-singular, so
    inverting it directly produces a Mahalanobis distance dominated by noise directions. Shrinking
    toward a scaled identity is the standard remedy and needs no extra data.
    """
    import torch

    n, d = centered.shape
    empirical = (centered.T @ centered) / max(n - 1, 1)
    mu = float(torch.trace(empirical) / d)
    target = mu * torch.eye(d, dtype=empirical.dtype, device=empirical.device)

    # Ledoit-Wolf coefficient: the ratio of the expected estimation error to the distance between
    # the empirical covariance and the shrinkage target.
    delta = float(torch.sum((empirical - target) ** 2))
    beta = float(sum(torch.sum((torch.outer(row, row) - empirical) ** 2) for row in centered) / (n**2))
    shrinkage = 0.0 if delta <= 0 else max(0.0, min(1.0, beta / delta))
    return (1.0 - shrinkage) * empirical + shrinkage * target, shrinkage


def build_bank(
    embeddings: Any,
    source: str = "",
    heldout_fraction: float = HELDOUT_FRACTION,
    seed: int = 0,
) -> CorpusEmbeddingBank:
    """Fit a bank from ``(N, D)`` pooled reference embeddings.

    Args:
        embeddings: Pooled image-token embeddings, one row per reference observation.
        source: Provenance string recorded on the bank.
        heldout_fraction: Fraction reserved to calibrate the in-distribution score distribution.
        seed: Seed for the fit/held-out split, so the calibration is reproducible.

    Returns:
        A fitted bank whose held-out scores calibrate the percentile of any new observation.
    """
    import torch

    matrix = embeddings.detach().float()
    assert matrix.ndim == 2, f"expected (N, D) embeddings, got {tuple(matrix.shape)}"
    n_total, dimension = matrix.shape
    assert n_total >= 4, f"need at least 4 reference embeddings to fit and calibrate, got {n_total}"

    generator = torch.Generator().manual_seed(seed)
    permutation = torch.randperm(n_total, generator=generator)
    n_heldout = max(1, int(round(heldout_fraction * n_total)))
    heldout_index, fit_index = permutation[:n_heldout], permutation[n_heldout:]
    fit, heldout = matrix[fit_index], matrix[heldout_index]

    mean = fit.mean(dim=0)
    covariance, shrinkage = _ledoit_wolf_shrinkage(fit - mean)
    # pinv rather than inverse: even after shrinkage the matrix can be ill-conditioned when
    # N is close to D, and a silent numerical failure here would corrupt every later score.
    precision = torch.linalg.pinv(covariance)
    normalized_bank = torch.nn.functional.normalize(fit, dim=1)

    bank = CorpusEmbeddingBank(
        mean=mean,
        precision=precision,
        normalized_bank=normalized_bank,
        raw_bank=fit,
        source=source,
        num_fit=int(fit.shape[0]),
        num_heldout=int(heldout.shape[0]),
        shrinkage=shrinkage,
    )

    # Calibrate on the held-out slice, which the fit never saw, so the percentiles describe genuine
    # in-distribution variation rather than the fit's own reconstruction error.
    collected: dict[str, list[float]] = {metric: [] for metric in METRICS}
    for row in heldout:
        scores = bank.score(row)
        for metric in METRICS:
            collected[metric].append(getattr(scores, metric))
    bank.heldout_scores = collected
    return bank


def auroc(in_distribution: list[float], out_of_distribution: list[float]) -> float:
    """Return the AUROC for separating OOD from ID scores, where higher scores mean more OOD.

    Computed as the Mann-Whitney U statistic normalised by the pair count, with ties at half
    credit. 0.5 means the score carries no information, which is the outcome that would refute the
    whole approach and so must be reported rather than smoothed over.
    """
    if not in_distribution or not out_of_distribution:
        return float("nan")
    wins = 0.0
    for ood in out_of_distribution:
        for idv in in_distribution:
            if ood > idv:
                wins += 1.0
            elif ood == idv:
                wins += 0.5
    return wins / (len(in_distribution) * len(out_of_distribution))


def evaluate_separation(bank: CorpusEmbeddingBank, target_embeddings: Any) -> dict[str, Any]:
    """Score target observations against the bank and report AUROC per metric.

    Args:
        bank: A fitted bank.
        target_embeddings: ``(M, D)`` pooled embeddings from the scene under test.

    Returns:
        Per-metric AUROC, mean target percentile, and the calibrated thresholds. An AUROC near 0.5
        means the representation does not distinguish the scenes.
    """
    scored = [bank.score(row) for row in target_embeddings.detach().float()]
    report: dict[str, Any] = {"num_target": len(scored), "bank": bank.summary(), "metrics": {}}
    for metric in METRICS:
        target_values = [getattr(s, metric) for s in scored]
        report["metrics"][metric] = {
            "auroc": round(auroc(bank.heldout_scores.get(metric, []), target_values), 4),
            "target_mean": round(sum(target_values) / len(target_values), 6) if target_values else None,
            "id_threshold_p95": bank.threshold(metric),
            "target_mean_percentile": (
                round(sum(bank._percentile(metric, v) or 0.0 for v in target_values) / len(target_values), 3)
                if target_values
                else None
            ),
        }
    return report


def write_report(report: dict[str, Any], path: Path | str) -> Path:
    """Write a separation report as JSON."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return path
