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
from .editor_revision_storage import RevisionError, RevisionStorage, encode, key_id, request_hash

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
        self.views = {}
        self.source_views = {}
        self.revisions = RevisionStorage(self.state_dir)
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

    def index(self, *, protect_snapshot=None):
        rows = [
            {"id": key, "name": path.stem, "source": path.relative_to(self.root).as_posix(), "kind": "discovered_file"}
            for key, path in self.catalogue.items()
        ]
        for revision_id in self.revisions.ids():
            receipt, snapshot, export = self._revision(revision_id)
            self._protect(protect_snapshot, receipt, snapshot, export)
            revision = receipt["revision"]
            rows.append({"id": revision["open_source"]["id"], "name": "Editor revision " + revision_id,
                         "source": revision["open_source"]["id"], "kind": "editor_revision",
                         "revision_id": revision_id, "source_hash": revision["source_hash"],
                         "canonical_hash": revision["canonical_hash"]})
        return rows

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
        if document_id is not None and document_id not in self.views:
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

    def issue_research_view(self, bundle, origin, identity, *, protect_snapshot=None):
        """Issue a fresh path-free view from a trusted verified research source artifact."""
        from .research_registry import digest as research_digest
        from .research_source import source_kind, verify_editor_source

        if source_kind(identity["source"]) == "editor_revision":
            bundle = verify_editor_source(identity["source"], bundle, protect_snapshot=protect_snapshot)
        else:
            receipt = json.loads(encode(bundle))
            if research_digest(receipt) != identity["source"]["receipt_sha256"]:
                raise ValueError("Candidate receipt conflict")
            text = receipt["yaml_text"]
            validation = self.validate(text)
            if not validation["valid"]:
                raise ValueError("Candidate source context unavailable")
            # An ephemeral view of the actual candidate receipt, not an editor revision.
            bundle = {"receipt": receipt, "snapshot": {"yaml_text": text, "includes": {},
                      "source_hash": digest(text), "canonical_hash": validation["canonical_hash"]}, "export_yaml": text}
            self._protect(protect_snapshot, receipt, bundle["snapshot"], text, decoded=True)
        view_id = uuid.uuid4().hex
        snapshot = bundle["snapshot"]
        self.frozen[view_id] = dict(snapshot["includes"])
        self.views[view_id] = {"source_hash": snapshot["source_hash"], "origin": dict(origin),
                              "research_bundle": bundle, "research_identity": json.loads(encode(identity))}
        return self.load(view_id, protect_snapshot=protect_snapshot)

    def load(self, document_id, *, protect_snapshot=None):
        """Open an exact source; reloading an issued immutable view retains its UUID and frozen bytes."""
        issued = self.views.get(document_id)
        if issued is not None and "research_bundle" in issued:
            bundle = issued["research_bundle"]
            self._protect(protect_snapshot, bundle["receipt"], bundle["snapshot"], bundle["export_yaml"], decoded=True)
            snapshot = bundle["snapshot"]
            return {"document_id": document_id, "source": issued["origin"]["id"],
                    "source_origin": dict(issued["origin"]), "research_identity": json.loads(encode(issued["research_identity"])),
                    "yaml_text": snapshot["yaml_text"], "source_hash": snapshot["source_hash"],
                    "validation": self.validate(snapshot["yaml_text"], document_id)}
        source_id = issued["origin"]["id"] if issued is not None else document_id
        if isinstance(source_id, str) and source_id.startswith("editor-revision:"):
            receipt, snapshot, export = self._revision(source_id.removeprefix("editor-revision:"))
            self._protect(protect_snapshot, receipt, snapshot, export)
            if issued is not None:
                if (issued["source_hash"] != snapshot["source_hash"]
                        or self.frozen[document_id] != snapshot["includes"]):
                    raise RevisionError("Issued editor revision view changed")
                view_id = document_id
            else:
                view_id = uuid.uuid4().hex
                self.frozen[view_id] = dict(snapshot["includes"])
                self.views[view_id] = {"source_hash": snapshot["source_hash"], "origin": receipt["revision"]["open_source"]}
            return {"document_id": view_id, "source": source_id, "source_origin": receipt["revision"]["open_source"],
                    "yaml_text": snapshot["yaml_text"], "source_hash": snapshot["source_hash"],
                    "validation": self.validate(snapshot["yaml_text"], view_id)}
        path = self.path(document_id)
        text = self.read_source(path)
        source_origin = {"kind": "discovered_file", "id": digest(path.relative_to(self.root).as_posix())[:32]}
        try:
            includes = self.freeze_source(document_id, text)
            # A view ID binds includes without conflating the raw source hash with the spec digest.
            view_id = digest(json.dumps([path.relative_to(self.root).as_posix(), text, includes], sort_keys=True))[:32]
            self.paths[view_id] = path
            self.frozen[view_id] = includes
            self.source_views[view_id] = digest(text)
            self.frozen.setdefault(document_id, includes)
            document_id = view_id
        except (ValueError, yaml.YAMLError, OSError):
            pass  # Validation returns the bounded source/include error without accepting a draft.
        return {
            "document_id": document_id,
            "source": path.relative_to(self.root).as_posix(),
            "source_origin": source_origin,
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

    def save(self, text, document_id=None, expected_source_hash=None, *, idempotency_key=None, protect_snapshot=None):
        if idempotency_key is not None:
            return self._save_keyed(text, document_id, expected_source_hash, idempotency_key, protect_snapshot)
        if expected_source_hash is not None:
            self._check_source_fresh(document_id, expected_source_hash)
        validation = self.validate(text, document_id)
        if not validation["valid"]:
            raise ValueError("Invalid environment specification: " + "; ".join(validation["errors"]))
        revision_id = uuid.uuid4().hex
        directory = self.state_dir / "editor-revisions" / revision_id
        snapshot = {
            "yaml_text": text,
            "includes": dict(self.frozen.get(document_id, {})),
            "source_hash": digest(text),
            "canonical_hash": validation["canonical_hash"],
            "document_id": document_id,
        }
        export = "# Flattened immutable Arena editor export (includes resolved).\n" + yaml.safe_dump(
            validation["spec"], sort_keys=False
        )
        self._protect(protect_snapshot, None, snapshot, export)
        if expected_source_hash is not None:
            self._check_source_fresh(document_id, expected_source_hash)
        directory.mkdir(parents=True, mode=0o700)
        (directory / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False), encoding="utf-8")
        (directory / "export.yaml").write_text(export, encoding="utf-8")
        return {
            "revision_id": revision_id,
            "yaml_text": text,
            "source_hash": digest(text),
            "canonical_hash": validation["canonical_hash"],
            "download_url": f"/api/editor/revisions/{revision_id}/download",
        }

    def download(self, revision_id, *, protect_snapshot=None):
        if not re.fullmatch(r"[a-f0-9]{32}", revision_id):
            raise KeyError("Revision not found")
        try:
            receipt, snapshot, export = self._revision(revision_id)
        except KeyError:
            pass
        else:
            self._protect(protect_snapshot, receipt, snapshot, export)
            return export
        snapshot, export = self.revisions.legacy(revision_id)
        self._protect(protect_snapshot, None, snapshot, export)
        return export

    def has_document(self, document_id):
        """Return whether an issued view or repository document exists, without inventing paths."""
        return document_id in self.views or document_id in self.paths

    def resolve_view(self, document_id):
        """Check an issued document capability; immutable views do not have filesystem paths."""
        if document_id in self.views:
            return dict(self.views[document_id])
        path = self.path(document_id)
        return {"origin": {"kind": "discovered_file", "id": digest(path.relative_to(self.root).as_posix())[:32]},
                "source": path.relative_to(self.root).as_posix()}

    def _revision(self, revision_id, sync=True, area=None):
        receipt, snapshot, export = (self.revisions.read(revision_id, sync) if area is None
                                     else self.revisions.read_at(area, revision_id, sync))
        self._verify_revision_parts(revision_id, receipt, snapshot, export)
        return receipt, snapshot, export

    def load_revision_bundle(self, revision_id, *, protect_snapshot=None):
        """Read a committed keyed revision as a detached, verified portable bundle.

        protect_snapshot receives a reject-only detached receipt/snapshot/export_yaml
        envelope plus decoded root/includes (including unused frozen includes).
        Legacy unkeyed exports are not committed bundles and are not promoted here.
        """
        receipt, snapshot, export = self._revision(revision_id)
        self._protect(protect_snapshot, receipt, snapshot, export, decoded=True)
        codec = "arena-editor-bundle/v1"
        return {"schema_version": 1, "codec": codec, "receipt": receipt, "snapshot": snapshot,
                "export_yaml": export,
                "bundle_sha256": hashlib.sha256(encode([codec, receipt, snapshot, export])).hexdigest()}

    @staticmethod
    def verify_revision_bundle(revision_id, bundle, *, protect_snapshot=None):
        """Verify portable v1 bytes/semantics without any source storage; return a detached copy.

        The digest is SHA256 of UTF-8 sorted compact finite non-ASCII-escaped JSON
        ["arena-editor-bundle/v1", receipt, snapshot, export_yaml]. It is not a scene hash.
        """
        try:
            if (type(bundle) is not dict or set(bundle) != {
                    "schema_version", "codec", "receipt", "snapshot", "export_yaml", "bundle_sha256"}
                    or type(bundle["schema_version"]) is not int or bundle["schema_version"] != 1
                    or bundle["codec"] != "arena-editor-bundle/v1"):
                raise ValueError
            raw = encode(bundle)
            if len(raw) > 6 * 1024 * 1024:
                raise ValueError
            bundle = json.loads(raw)
            receipt, snapshot, export = bundle["receipt"], bundle["snapshot"], bundle["export_yaml"]
            if bundle["bundle_sha256"] != hashlib.sha256(encode([bundle["codec"], receipt, snapshot, export])).hexdigest():
                raise ValueError
            Documents._verify_revision_parts(revision_id, receipt, snapshot, export)
        except (ValueError, TypeError, KeyError, RecursionError):
            raise RevisionError("Invalid editor revision bundle") from None
        Documents._protect(protect_snapshot, receipt, snapshot, export, decoded=True)
        return bundle

    @staticmethod
    def _verify_revision_parts(revision_id, receipt, snapshot, export):
        try:
            if type(receipt) is not dict or set(receipt) != {"schema_version", "idempotency_key", "request_sha256", "state", "revision"}:
                raise ValueError
            if (type(receipt["schema_version"]) is not int or receipt["schema_version"] != 1
                    or receipt["state"] != "committed" or key_id(receipt["idempotency_key"]) != revision_id):
                raise ValueError
            if type(snapshot) is not dict or set(snapshot) != {"yaml_text", "includes", "source_hash", "canonical_hash", "document_id", "expected_source_hash"}:
                raise ValueError
            text, includes = snapshot["yaml_text"], snapshot["includes"]
            if type(text) is not str or len(text.encode("utf-8")) > MAX_YAML_BYTES or type(includes) is not dict or len(includes) > 1:
                raise ValueError
            for name, included in includes.items():
                if type(name) is not str or Path(name).is_absolute() or type(included) is not str or len(included.encode("utf-8")) > MAX_YAML_BYTES:
                    raise ValueError
                if "external_yaml" in parse_yaml(included):
                    raise ValueError
            data = parse_yaml(text)
            include = data.pop("external_yaml", None)
            if include is not None:
                included = parse_yaml(includes[include])
                if data.keys() & included.keys():
                    raise ValueError
                data = {**included, **data}
            reject_unknown_fields(data)
            spec = ArenaEnvGraphSpec.from_dict(data).to_dict()
            if snapshot["source_hash"] != digest(text) or snapshot["canonical_hash"] != canonical_digest(spec):
                raise ValueError
            if receipt["request_sha256"] != request_hash(text, snapshot["document_id"], snapshot["expected_source_hash"]):
                raise ValueError
            expected = Documents._revision_record(revision_id, text, snapshot["canonical_hash"])
            if receipt["revision"] != expected or export != Documents._export(spec):
                raise ValueError
        except (ValueError, TypeError, KeyError, RecursionError, yaml.YAMLError, AssertionError):
            raise RevisionError("Invalid editor revision bundle") from None
        return receipt, snapshot, export

    @staticmethod
    def _export(spec):
        return "# Flattened immutable Arena editor export (includes resolved).\n" + yaml.safe_dump(spec, sort_keys=False)

    @staticmethod
    def _revision_record(revision_id, text, canonical_hash):
        return {"revision_id": revision_id, "yaml_text": text, "source_hash": digest(text),
                "canonical_hash": canonical_hash, "download_url": f"/api/editor/revisions/{revision_id}/download",
                "open_source": {"kind": "editor_revision", "id": "editor-revision:" + revision_id}}

    def save_request(self, key, *, protect_snapshot=None):
        """Read a committed workspace-global request; missing and incomplete are distinct."""
        receipt, snapshot, export = self._revision(key_id(key), sync=True)
        if receipt["idempotency_key"] != key:
            raise RevisionError("Editor idempotency key conflict")
        self._protect(protect_snapshot, receipt, snapshot, export)
        return receipt

    @staticmethod
    def _protect(callback, receipt, snapshot, export, *, decoded=False):
        if callback is not None:
            value = {"receipt": receipt, "snapshot": snapshot, "export_yaml": export}
            if decoded:
                value["decoded"] = {"root": parse_yaml(snapshot["yaml_text"]),
                                    "includes": {name: parse_yaml(text) for name, text in snapshot["includes"].items()}}
            before = encode(value)
            detached = json.loads(before)
            # Invocation is deliberately outside the normalization boundary:
            # a caller's secret-rejection HTTPException must propagate unchanged.
            callback(detached)
            try:
                def check(value, depth=0):
                    if depth > 64:
                        raise ValueError
                    if type(value) is dict:
                        for key, child in value.items():
                            if type(key) is not str:
                                raise ValueError
                            check(child, depth + 1)
                    elif type(value) is list:
                        for child in value:
                            check(child, depth + 1)
                    elif value is not None and type(value) not in (str, int, float, bool):
                        raise ValueError
                check(detached)
                if encode(detached) != before:
                    raise ValueError
            except (TypeError, ValueError, RecursionError):
                raise RevisionError("Editor protection callback changed bundle") from None

    def _save_keyed(self, text, document_id, expected_source_hash, key, protect_snapshot):
        revision_id = key_id(key)
        request_sha256 = request_hash(text, document_id, expected_source_hash)
        with self.revisions.area(create=True, lock=True) as area:
            try:
                receipt, snapshot, export = self._revision(revision_id, sync=True, area=area)
            except KeyError:
                pass
            else:
                if receipt["idempotency_key"] != key or receipt["request_sha256"] != request_sha256:
                    raise RevisionError("Editor idempotency key conflict")
                self._protect(protect_snapshot, receipt, snapshot, export)
                return receipt
            self._check_source_fresh(document_id, expected_source_hash)
            self._protect_immutable_origin(document_id, protect_snapshot, area=area)
            validation = self.validate(text, document_id)
            if not validation["valid"]:
                raise RevisionError("Invalid environment specification")
            snapshot = {"yaml_text": text, "includes": dict(self.frozen.get(document_id, {})),
                        "source_hash": digest(text), "canonical_hash": validation["canonical_hash"],
                        "document_id": document_id, "expected_source_hash": expected_source_hash}
            receipt = {"schema_version": 1, "idempotency_key": key, "request_sha256": request_sha256,
                       "state": "committed", "revision": self._revision_record(revision_id, text, validation["canonical_hash"])}
            export = self._export(validation["spec"])
            self._protect(protect_snapshot, receipt, snapshot, export)
            self._check_source_fresh(document_id, expected_source_hash)
            self.revisions.commit(area, revision_id, receipt, snapshot, export)
            receipt, snapshot, export = self._revision(revision_id, sync=True, area=area)
            self._protect(protect_snapshot, receipt, snapshot, export)
            return receipt

    def _protect_immutable_origin(self, document_id, callback, *, area=None):
        """Protect the complete issued origin only for fresh work, never committed replay."""
        issued = self.views.get(document_id)
        if issued is None:
            return
        if "research_bundle" in issued:
            bundle = issued["research_bundle"]
            receipt, snapshot, export = bundle["receipt"], bundle["snapshot"], bundle["export_yaml"]
        elif issued["origin"]["kind"] == "editor_revision":
            # Reuse the held writer descriptor; a nested read lock would contend with ourselves.
            receipt, snapshot, export = self._revision(
                issued["origin"]["id"].removeprefix("editor-revision:"), area=area)
        else:
            return
        if issued["source_hash"] != snapshot["source_hash"] or self.frozen[document_id] != snapshot["includes"]:
            raise RevisionError("Issued immutable view changed")
        self._protect(callback, receipt, snapshot, export, decoded=True)

    def _check_source_fresh(self, document_id, expected_source_hash):
        if document_id is None and expected_source_hash is None:
            return
        try:
            if document_id in self.views:
                if expected_source_hash is not None and self.views[document_id]["source_hash"] != expected_source_hash:
                    raise RevisionError("Source changed; reload before saving a revision")
                return
            if document_id is None:
                raise RevisionError("Source changed; reload before saving a revision")
            path = self.path(document_id)
            baseline = self.source_views.get(document_id, expected_source_hash)
            if baseline is not None and (digest(self.read_source(path)) != baseline
                                         or (expected_source_hash is not None and baseline != expected_source_hash)):
                raise RevisionError("Source changed; reload before saving a revision")
            for name, frozen in self.frozen.get(document_id, {}).items():
                if self.read_source(path.parent / name) != frozen:
                    raise RevisionError("Included source changed; reload before saving a revision")
        except (OSError, KeyError):
            raise RevisionError("Source or included YAML is unavailable") from None
