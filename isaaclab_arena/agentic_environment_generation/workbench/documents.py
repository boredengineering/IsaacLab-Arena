# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only source documents and schema-backed authored graph projections."""

import hashlib
import json
import re
import uuid
import yaml
from pathlib import Path

from pydantic import ValidationError

from isaaclab_arena.environment_spec.arena_env_graph_spec import ArenaEnvGraphSpec

from .document_yaml import parse_yaml, reject_unknown_fields

MAX_YAML_BYTES = 256 * 1024
ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE = "isaaclab_arena/tests/test_data/pick_and_place_maple_table_env_graph.yaml"


def digest(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def canonical_digest(spec):
    """Return the shared canonical scene hash, preserving existing document identities."""
    return digest(json.dumps(spec, sort_keys=True, allow_nan=False))


def projection(spec):
    """Project authored assets and edges without synthesizing reification statements."""
    data = spec.to_dict()
    assets = []
    for role, entries in (
        ("embodiment", [data["embodiment"]]),
        ("background", [data["background"]]),
        ("object", data["objects"]),
        ("object_reference", data.get("object_references", [])),
    ):
        for entry in entries:
            assets.append({
                **{k: v for k, v in entry.items() if k in {"id", "registry_name", "parent_id", "prim_path"}},
                "role": role,
                "properties": entry,
            })
    nodes = [{"id": a["id"], "label": a["id"], "role": a["role"], "properties": a["properties"]} for a in assets]
    edges = []
    for a in assets:
        if a.get("parent_id"):
            edges.append({
                "id": f"parent:{a['id']}",
                "source": a["parent_id"],
                "target": a["id"],
                "label": "contains",
                "properties": {},
            })
    for index, relation in enumerate(data["relations"]):
        edges.append({
            "id": f"relation:{index}",
            "source": relation["subject"],
            "target": relation.get("reference") or relation["subject"],
            "label": relation["kind"],
            "properties": relation,
        })
    for relation in data.get("reified_relations", []):
        rid = relation["reifier_id"]
        nodes.append({"id": rid, "label": relation["relation_type"], "role": "reifier", "properties": relation})
        for endpoint, key in (("subject", "source_id"), ("object", "target_id")):
            edges.append({
                "id": f"{rid}:{endpoint}",
                "source": rid,
                "target": relation[key],
                "label": f"reifies_{endpoint}",
                "properties": {},
            })
    return {
        "spec": data,
        "summary": spec.summary(),
        "assets": assets,
        "graph": {"nodes": nodes, "edges": edges},
        "relations": data["relations"],
        "reified_relations": data.get("reified_relations", []),
        "tasks": data["task"]["subtasks"],
    }


class Documents:
    """Issue opaque IDs only for explicit repository source roots."""

    def __init__(self, state_dir, root=ROOT):
        self.state_dir = Path(state_dir)
        self.root = Path(root).resolve()
        self.paths = {}
        self.frozen = {}
        sources = [self.root / DEFAULT_SOURCE]
        for folder in ("generated_envs", "isaaclab_arena_environments"):
            directory = self.root / folder
            sources.extend(sorted(directory.rglob("*.yaml")))
            sources.extend(sorted(directory.rglob("*.yml")))
        for path in sources:
            if path.is_file() and path.resolve().is_relative_to(self.root) and not path.is_symlink():
                relative = path.relative_to(self.root).as_posix()
                self.paths[digest(relative)[:32]] = path
        self.default_document_id = digest(DEFAULT_SOURCE)[:32]
        self.catalogue = dict(self.paths)

    def index(self):
        return [
            {"id": key, "name": path.stem, "source": path.relative_to(self.root).as_posix()}
            for key, path in self.catalogue.items()
        ]

    def path(self, document_id):
        if document_id not in self.paths:
            raise KeyError("Document not found")
        path = self.paths[document_id]
        self.read_source(path)
        return path

    def read_source(self, path):
        allowed = (
            self.root / "generated_envs",
            self.root / "isaaclab_arena_environments",
            self.root / "isaaclab_arena/tests/test_data",
        )
        resolved = path.resolve()
        if not any(resolved.is_relative_to(root) for root in allowed) or path.is_symlink():
            raise ValueError("Source path is outside allowed document roots")
        with resolved.open("rb") as handle:
            data = handle.read(MAX_YAML_BYTES + 1)
        if len(data) > MAX_YAML_BYTES:
            raise ValueError("YAML exceeds 256 KiB")
        return data.decode("utf-8")

    def freeze_source(self, document_id, text):
        includes = {}
        name = parse_yaml(text).get("external_yaml")
        if name is not None:
            if not isinstance(name, str) or Path(name).is_absolute():
                raise ValueError("Include must be a relative YAML path")
            included = self.read_source(self.path(document_id).parent / name)
            data = parse_yaml(included)
            if "external_yaml" in data:
                raise ValueError("Nested external_yaml is not allowed")
            includes[name] = included
        return includes

    def resolve(self, text, document_id=None):
        data = parse_yaml(text)
        if document_id is not None:
            path = self.path(document_id)
            if document_id not in self.frozen:
                self.frozen[document_id] = self.freeze_source(document_id, self.read_source(path))
        include = data.pop("external_yaml", None)
        if include is not None:
            frozen = self.frozen.get(document_id, {})
            if not isinstance(include, str) or include not in frozen:
                raise ValueError("Include is not in this document's frozen source set; load the source document first")
            included = parse_yaml(frozen[include])
            if data.keys() & included.keys():
                raise ValueError("Duplicate env graph spec key across includes")
            data = {**included, **data}
        reject_unknown_fields(data)
        return data

    def load(self, document_id):
        path = self.path(document_id)
        text = self.read_source(path)
        try:
            includes = self.freeze_source(document_id, text)
            # A view ID binds includes without conflating the raw source hash with the spec digest.
            view_id = digest(json.dumps([path.relative_to(self.root).as_posix(), text, includes], sort_keys=True))[:32]
            self.paths[view_id] = path
            self.frozen[view_id] = includes
            self.frozen.setdefault(document_id, includes)
            document_id = view_id
        except (ValueError, yaml.YAMLError, OSError):
            pass  # Validation returns the bounded source/include error without accepting a draft.
        return {
            "document_id": document_id,
            "source": path.relative_to(self.root).as_posix(),
            "yaml_text": text,
            "source_hash": digest(text),
            "validation": self.validate(text, document_id),
        }

    def validate(self, text, document_id=None):
        result = {
            "valid": False,
            "source_hash": digest(text),
            "canonical_hash": None,
            "errors": [],
            "warnings": [],
            "spec": None,
            "summary": "Invalid environment specification",
            "graph": {"nodes": [], "edges": []},
            "assets": [],
            "relations": [],
            "reified_relations": [],
            "tasks": [],
        }
        try:
            if len(text.encode("utf-8")) > MAX_YAML_BYTES:
                raise ValueError("YAML exceeds 256 KiB")
            spec = ArenaEnvGraphSpec.from_dict(self.resolve(text, document_id))
            result.update(projection(spec))
            result.update(valid=True, canonical_hash=canonical_digest(spec.to_dict()))
            result["warnings"] = ["Schema validation does not certify physical stability or task success."]
        except ValidationError as error:
            result["errors"] = [
                f"{'.'.join(map(str, e['loc']))}: {e['msg']}" for e in error.errors(include_input=False)
            ]
        except OSError:
            result["errors"] = ["Source or included YAML is unavailable"]
        except (ValueError, AssertionError, yaml.YAMLError, TypeError, KeyError) as error:
            result["errors"] = [str(error)[:2000]]
        return result

    def save(self, text, document_id=None, expected_source_hash=None):
        if expected_source_hash is not None:
            if document_id is None or digest(self.read_source(self.path(document_id))) != expected_source_hash:
                raise ValueError("Source changed; reload before saving a revision")
            for name, frozen in self.frozen.get(document_id, {}).items():
                if self.read_source(self.path(document_id).parent / name) != frozen:
                    raise ValueError("Included source changed; reload before saving a revision")
        validation = self.validate(text, document_id)
        if not validation["valid"]:
            raise ValueError("Invalid environment specification: " + "; ".join(validation["errors"]))
        revision_id = uuid.uuid4().hex
        directory = self.state_dir / "editor-revisions" / revision_id
        directory.mkdir(parents=True, mode=0o700)
        snapshot = {
            "yaml_text": text,
            "includes": self.frozen.get(document_id, {}),
            "source_hash": digest(text),
            "canonical_hash": validation["canonical_hash"],
            "document_id": document_id,
        }
        export = "# Flattened immutable Arena editor export (includes resolved).\n" + yaml.safe_dump(
            validation["spec"], sort_keys=False
        )
        (directory / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        (directory / "export.yaml").write_text(export, encoding="utf-8")
        return {
            "revision_id": revision_id,
            "yaml_text": text,
            "source_hash": digest(text),
            "canonical_hash": validation["canonical_hash"],
            "download_url": f"/api/editor/revisions/{revision_id}/download",
        }

    def download(self, revision_id):
        if not re.fullmatch(r"[a-f0-9]{32}", revision_id):
            raise KeyError("Revision not found")
        path = self.state_dir / "editor-revisions" / revision_id / "export.yaml"
        if not path.is_file() or path.is_symlink() or path.parent.is_symlink():
            raise KeyError("Revision not found")
        return path.read_text(encoding="utf-8")
