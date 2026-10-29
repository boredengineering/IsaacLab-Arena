# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure projection contracts; no database or simulation evidence."""

import importlib
import json
from copy import deepcopy

import pytest

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec
from isaaclab_arena.environment_spec.arena_env_graph_types import AssetRegistry, TaskRegistry


@pytest.fixture
def spec(monkeypatch):
    monkeypatch.setattr(AssetRegistry, "is_registered", lambda *args: True)
    monkeypatch.setattr(TaskRegistry, "is_registered", lambda *args: True)
    return ArenaEnvGraphSpec.from_dict({
        "env_name": "synthetic_场景",
        "embodiment": {"id": "robot", "registry_name": "synthetic"},
        "background": {"id": "table", "registry_name": "synthetic"},
        "objects": [{"id": "apple", "registry_name": "synthetic", "params": {"x": 0.0}}],
        "task": {
            "subtasks": [{"kind": "SyntheticTask", "params": {"pick_up_object": "apple", "background_scene": "table"}}]
        },
    })


def module():
    return importlib.import_module("isaaclab_arena.agentic_environment_generation.workbench.research_projection")


def project(spec, **kwargs):
    return module().project_scene(
        spec,
        **{"revision_id": "revision-1", "store_id": "store-1", "family": "scenario-family", "version": "v7", **kwargs},
    )


def test_supported_identity_preserves_dcrg_root_and_both_hashes(spec):
    from isaaclab_arena.agentic_environment_generation.dcrg.graph import graph_identity
    from isaaclab_arena.agentic_environment_generation.workbench.documents import canonical_digest

    original = deepcopy(spec.to_dict())
    result = project(spec)
    identity = graph_identity(spec, target_object_id="apple")
    assert result["canonical_identity"] == {"name": identity["env_name"], "sha256": identity["version"]}
    assert result["hashes"]["workbench"]["sha256"] == canonical_digest(original)
    assert result["hashes"]["dcrg"]["sha256"] == identity["version"]
    assert result["hashes"]["workbench"]["sha256"] != result["hashes"]["dcrg"]["sha256"]
    assert result["hashes"]["workbench"]["separators"] == [", ", ": "]
    assert result["hashes"]["dcrg"]["separators"] == [",", ":"]
    root = next(node for node in result["nodes"] if node["labels"] == ["EnvironmentGraph"])
    assert root["properties"] == {
        "name": identity["env_name"],
        "version": identity["version"],
        "spec_sha256": identity["version"],
        "spec_json": json.dumps(original, sort_keys=True, separators=(",", ":"), allow_nan=False),
        "source_env_name": spec.env_name,
    }
    assert result["scope"]["internal_env_name"] == spec.env_name
    assert result["scope"]["family"] == "scenario-family"
    assert {edge["type"] for edge in result["edges"]} >= {"HAS_EMBODIMENT", "HAS_TERRAIN", "CONTAINS_OBJECT"}
    assert not any("ReifiedRelation" in node["labels"] for node in result["nodes"])
    assert spec.to_dict() == original
    assert result == project(spec)
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_unsupported_scene_projects_only_authored_relations_and_references(spec):
    from isaaclab_arena.environment_spec.arena_env_graph_types import (
        ObjectReferenceSpec,
        ReifiedRelationSpec,
        SpatialRelationSpec,
    )

    spec.task.subtasks[0].params = {"door": "apple"}
    spec.objects[0].registry_name = "X` MATCH (n) DETACH DELETE n //"
    spec.embodiment.params["camera"] = {"prim_path": "/Robot/Camera", "resolution": [64, 32]}
    spec.object_references = [
        ObjectReferenceSpec(id="surface", parent_id="table", prim_path="/Table/Top", object_type="base")
    ]
    spec.relations = [
        SpatialRelationSpec.model_construct(
            kind="hostile`]->() //", subject="apple", reference="surface", params={"surface_anchor": "top"}
        )
    ]
    spec.reified_relations = [
        ReifiedRelationSpec(reifier_id="authored", source_id="apple", target_id="surface", relation_type="AUTHORED")
    ]
    result = project(spec)
    assert result["dcrg_mapping"]["status"] == "unsupported"
    assert result["canonical_identity"]["name"].startswith("workbench__")
    assert result["canonical_identity"]["name"].endswith(result["canonical_identity"]["sha256"])
    assert len([n for n in result["nodes"] if "ReifiedRelation" in n["labels"]]) == 1
    assert any("USDPrim" in n["labels"] and n["properties"]["prim_path"] == "/Table/Top" for n in result["nodes"])
    assert any("SurfaceAnchor" in n["labels"] for n in result["nodes"])
    assert any(
        e["type"] == "AUTHORED_RELATION" and e["properties"]["kind"] == "hostile`]->() //" for e in result["edges"]
    )
    assert not any("Camera" in n["labels"] for n in result["nodes"])  # No typed camera schema.
    assert "camera" in next(n for n in result["nodes"] if "Embodiment" in n["labels"])["properties"]["params_json"]
    assert "legacy" in result["retrieval_limitations"].lower()
    other = project(spec, revision_id="revision-2")
    assert result["canonical_identity"] == other["canonical_identity"]
    assert set(result["asset_mapping"].values()).isdisjoint(other["asset_mapping"].values())
    spec.relations[0].reference = "table"
    assert project(spec)["canonical_identity"] != result["canonical_identity"]


def test_supported_mapping_checks_every_explicit_target_without_inventing_support(spec):
    spec.task.subtasks[0].params.pop("background_scene")
    result = project(spec)
    assert result["dcrg_mapping"]["status"] == "unsupported"
    assert result["dcrg_mapping"]["targets"][0]["status"] == "unsupported"
    assert not any("ReifiedRelation" in n["labels"] for n in result["nodes"])


def test_reifiers_use_physical_scoped_keys_compatible_with_dcrg_uniqueness(spec):
    from isaaclab_arena.environment_spec.arena_env_graph_types import ReifiedRelationSpec

    spec.reified_relations = [
        ReifiedRelationSpec(reifier_id="support_apple", source_id="apple", target_id="table", relation_type="PLACED_ON")
    ]
    first, second = project(spec), project(spec, revision_id="other")
    a = next(n for n in first["nodes"] if "ReifiedRelation" in n["labels"])
    b = next(n for n in second["nodes"] if "ReifiedRelation" in n["labels"])
    assert a["key"]["reifier_id"] != b["key"]["reifier_id"]
    assert a["properties"]["authored_reifier_id"] == "support_apple"
    assert first["dcrg_mapping"]["targets"][0]["reifier_id"] == "support_apple"


@pytest.mark.parametrize(
    "change",
    [
        "duplicate_node",
        "duplicate_edge",
        "missing_node",
        "missing_edge",
        "extra_node",
        "endpoint",
        "property",
        "label",
        "digest",
        "scope",
        "collision",
    ],
)
def test_exact_readback_rejects_corruption_even_with_copied_digests(spec, change):
    expected = project(spec)
    module().validate_projection(expected, spec=spec)
    module().compare_readback(expected, expected["nodes"], expected["edges"], spec=spec)
    bad = deepcopy(expected)
    if change == "duplicate_node":
        bad["nodes"].append(deepcopy(bad["nodes"][0]))
    elif change == "duplicate_edge":
        bad["edges"].append(deepcopy(bad["edges"][0]))
    elif change == "missing_node":
        bad["nodes"].pop()
    elif change == "missing_edge":
        bad["edges"].pop()
    elif change == "extra_node":
        bad["nodes"].append({**deepcopy(bad["nodes"][0]), "id": "extra"})
    elif change == "endpoint":
        bad["edges"][0]["target"] = bad["edges"][0]["source"]
    elif change == "property":
        bad["nodes"][0]["properties"]["injected"] = "bad"
    elif change == "label":
        bad["nodes"][0]["labels"].append("EVIL")
    elif change == "digest":
        bad["nodes"][0]["digest"] = "0" * 64
    elif change == "scope":
        bad["nodes"][0]["key"]["scope_id"] = "another-revision"
    elif change == "collision":
        root = next(n for n in bad["nodes"] if n["labels"] == ["EnvironmentGraph"])
        root["properties"]["spec_sha256"] = expected["canonical_identity"]["sha256"][:16] + "0" * 48
    with pytest.raises(ValueError):
        module().compare_readback(expected, bad["nodes"], bad["edges"], spec=spec)
    with pytest.raises(ValueError):
        module().validate_projection(bad, spec=spec)


def test_validation_checks_source_semantics_not_only_self_consistent_hashes(spec):
    original = project(spec)
    changed = spec.model_copy(deep=True)
    changed.objects[0].params["x"] = 0.2
    with pytest.raises(ValueError):
        module().validate_projection(project(changed), spec=spec)
    assert project(changed)["canonical_identity"] != original["canonical_identity"]
    root = next(n for n in original["nodes"] if n["labels"] == ["EnvironmentGraph"])
    existing = {**root["properties"], "unrelated_metadata": "preserve"}
    before = deepcopy(existing)
    module().check_root_compatibility(original, [existing])
    assert existing == before
    with pytest.raises(ValueError):
        module().check_root_compatibility(original, [existing, existing])
    existing["version"] = "0" * 64
    with pytest.raises(ValueError):
        module().check_root_compatibility(original, [existing])


@pytest.mark.parametrize(
    "value",
    [
        float("nan"),
        float("inf"),
        -float("inf"),
        2**64,
        "x" * (256 * 1024 + 1),
        {"deep": [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]},
    ],
)
def test_projection_bounds_and_finiteness(spec, value):
    spec.objects[0].params["bad"] = value
    with pytest.raises(ValueError):
        project(spec)


def hydrated_extras():
    from datetime import timedelta, timezone

    import pytz
    from neo4j.spatial import CartesianPoint, WGS84Point
    from neo4j.time import Date, DateTime, Duration, Time

    return [
        DateTime(2026, 9, 14, 12, 30, 0, 123456789),
        Date(2026, 9, 14),
        Duration(months=2, days=3, seconds=4, nanoseconds=5),
        Time(12, 30, 0),
        CartesianPoint((1.0, 2.0, 3.0)),
        WGS84Point((10.0, 20.0)),
        b"metadata",
        DateTime(2026, 9, 14, tzinfo=pytz.UTC),
        DateTime(2026, 9, 14, tzinfo=pytz.timezone("Europe/London")),
        Time(12, 30, tzinfo=timezone(timedelta(hours=2))),
        DateTime(2026, 9, 14, tzinfo=pytz.FixedOffset(120)),
    ]


@pytest.mark.parametrize("extra", hydrated_extras())
def test_hydrated_root_extras_are_tolerated_without_mutation(spec, extra):
    projection = project(spec)
    root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
    actual = {**root, "created_at": extra}
    module().check_root_compatibility(projection, [actual])
    assert actual["created_at"] is extra
    assert {k: actual[k] for k in root} == root


@pytest.mark.parametrize("field", ["name", "version", "spec_sha256", "spec_json", "source_env_name"])
def test_hydrated_value_never_normalizes_owned_canonical_fields(spec, field):
    projection = project(spec)
    root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
    with pytest.raises(ValueError):
        module().check_root_compatibility(projection, [{**root, field: hydrated_extras()[0]}])


@pytest.mark.parametrize("extra", [object(), {"bad": object()}, "x" * (4 * 1024 * 1024 + 1), [0] * 4097, float("nan")])
def test_unsafe_root_extras_fail_closed(spec, extra):
    projection = project(spec)
    root = next(n["properties"] for n in projection["nodes"] if n["labels"] == ["EnvironmentGraph"])
    with pytest.raises(ValueError):
        module().check_root_compatibility(projection, [{**root, "extra": extra}])


def test_raw_inspection_bounds_cycles_aggregate_and_spatial_values():
    from neo4j.spatial import CartesianPoint

    cyclic = []
    cyclic.append(cyclic)
    for value, limit in [(cyclic, 4096), (["x" * 100] * 100, 1024), (CartesianPoint((float("nan"), 2.0)), 4096)]:
        with pytest.raises(ValueError):
            module().bounded_neo4j_value(value, max_bytes=limit)


def test_unknown_temporal_timezone_fails_without_executing_methods():
    from datetime import tzinfo

    from neo4j.time import DateTime

    class HostileZone(tzinfo):
        def tzname(self, dt):
            raise AssertionError("must not call unknown timezone")

    with pytest.raises(ValueError, match="Unsupported temporal timezone"):
        module().bounded_neo4j_value(DateTime(2026, 9, 14, tzinfo=HostileZone()))


def test_projection_rejects_record_count_and_empty_scope(spec):
    spec.objects = [spec.objects[0].model_copy(update={"id": f"object-{i}"}) for i in range(4097)]
    with pytest.raises(ValueError):
        project(spec)
    with pytest.raises(ValueError):
        project(spec, revision_id="")


def test_projection_exposes_authored_reifier_mapping_and_rejects_wide_params(spec):
    from isaaclab_arena.environment_spec.arena_env_graph_types import ReifiedRelationSpec

    spec.reified_relations = [
        ReifiedRelationSpec(reifier_id="support_apple", source_id="apple", target_id="table", relation_type="PLACED_ON")
    ]
    result = project(spec)
    node_id = result["reifier_mapping"]["support_apple"]
    assert (
        next(n for n in result["nodes"] if n["id"] == node_id)["properties"]["authored_reifier_id"] == "support_apple"
    )
    spec.objects[0].params = {str(i): i for i in range(4097)}
    with pytest.raises(ValueError, match="collection bound"):
        project(spec)
