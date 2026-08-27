# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""SHACL validation helper for RDF-star environment graphs."""

from __future__ import annotations

from pathlib import Path
import rdflib
import pyshacl

DEFAULT_SHACL_PATH = Path(__file__).parent / "ontology" / "arena_constraints.shacl.ttl"


def validate_rdf_environment_graph(
    data_graph: rdflib.Graph,
    shacl_path: Path | str = DEFAULT_SHACL_PATH,
) -> tuple[bool, str]:
    """Validate an RDF-star environment graph against the arena SHACL constraint shapes.

    Args:
        data_graph: An rdflib Graph containing the parsed scene and entities.
        shacl_path: Filesystem path to the SHACL constraint rules (.ttl).

    Returns:
        A tuple ``(conforms, report_text)``. When ``conforms`` is False, ``report_text``
        contains the detailed human-readable validation violations.
    """
    shacl_graph = rdflib.Graph()
    shacl_graph.parse(str(shacl_path), format="turtle")

    conforms, results_graph, results_text = pyshacl.validate(
        data_graph,
        shacl_graph=shacl_graph,
        inference="rdfs",
        abort_on_first=False,
        meta_shacl=False,
        advanced=True,
    )
    return bool(conforms), str(results_text)
