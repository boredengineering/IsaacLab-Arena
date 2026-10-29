# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded Linux-local editor bundles; manifest promotion is the commit point.

This is a durability boundary, not an ACL against the same trusted OS identity.
Incomplete directories remain evidence and are never repaired. Legacy exports
live in a different namespace and cannot be mistaken for committed receipts.
"""

import contextlib
import fcntl
import hashlib
import json
import os
import re
import time
import uuid

from . import research_artifacts as artifacts

MAX_BUNDLE_FILE = 2 * 1024 * 1024
MAX_REVISIONS = 4096
LOCK_SECONDS = 2.0


class RevisionError(ValueError):
    """Static, payload-free invalid request, conflict, or corrupt bundle error."""


class RevisionBusy(RuntimeError):
    """Another cooperative editor writer holds the bounded transaction lock."""


class RevisionUncertain(RuntimeError):
    """A storage operation failed; inspect or retry the exact request."""


def encode(value):
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (ValueError, TypeError, RecursionError):
        raise RevisionError("Invalid editor revision JSON") from None


def sha(data):
    return hashlib.sha256(data).hexdigest()


def request_hash(text, document_id, expected_source_hash):
    if type(text) is not str or (document_id is not None and
                               (type(document_id) is not str or not re.fullmatch("[a-f0-9]{32}", document_id))):
        raise RevisionError("Invalid editor save request")
    try:
        if len(text.encode("utf-8")) > 256 * 1024:
            raise RevisionError("Editor YAML exceeds bounds")
    except UnicodeError:
        raise RevisionError("Invalid editor save Unicode") from None
    if expected_source_hash is not None and (type(expected_source_hash) is not str or not re.fullmatch("[a-f0-9]{64}", expected_source_hash)):
        raise RevisionError("Invalid editor source hash")
    return sha(encode(["editor-save/v1", text, document_id, expected_source_hash]))


def key_id(key):
    if type(key) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9:._-]{0,127}", key):
        raise RevisionError("Invalid editor idempotency key")
    return sha(key.encode("ascii"))[:32]


class RevisionStorage:
    """Open a no-follow private bundle area only when needed."""

    def __init__(self, state_dir):
        self.path = state_dir / "editor-revision-bundles"

    @contextlib.contextmanager
    def area(self, create=False, lock=False):
        fd = None
        try:
            if create:
                # Validate the existing state root before creating its managed child.
                parent = artifacts._root(self.path.parent, False)
                try:
                    try:
                        os.mkdir(self.path.name, 0o700, dir_fd=parent)
                    except FileExistsError:
                        pass
                    else:
                        os.fsync(parent)
                except OSError:
                    raise RevisionUncertain("Editor revision area creation uncertain; retry exact request") from None
                finally:
                    os.close(parent)
            fd = artifacts._root(self.path, False)
            if lock:
                deadline = time.monotonic() + LOCK_SECONDS
                while True:
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                        break
                    except BlockingIOError:
                        if time.monotonic() >= deadline:
                            raise RevisionBusy("Editor revision writer busy") from None
                        time.sleep(0.01)
            yield fd
        except FileNotFoundError:
            raise
        except (artifacts.ArtifactError, OSError):
            raise RevisionError("Unsafe editor revision storage") from None
        finally:
            if fd is not None:
                os.close(fd)

    def read_at(self, area, revision_id, sync=False):
        if type(revision_id) is not str or not re.fullmatch("[a-f0-9]{32}", revision_id):
            raise RevisionError("Invalid editor revision identifier")
        try:
            with artifacts._directory(area, revision_id) as directory:
                try:
                    manifest_raw = artifacts._read(directory, "manifest.json", MAX_BUNDLE_FILE)
                    manifest = json.loads(manifest_raw)
                    if (type(manifest) is not dict or set(manifest) != {"schema_version", "receipt", "files"}
                            or type(manifest["schema_version"]) is not int or manifest["schema_version"] != 1):
                        raise RevisionError("Invalid editor revision manifest")
                    if encode(manifest) != manifest_raw:
                        raise RevisionError("Invalid editor revision manifest")
                    if type(manifest["files"]) is not dict or set(manifest["files"]) != {"snapshot.json", "export.yaml"}:
                        raise RevisionError("Invalid editor revision manifest")
                    payloads = {}
                    for name, descriptor in manifest["files"].items():
                        if type(descriptor) is not dict or set(descriptor) != {"bytes", "sha256"}:
                            raise RevisionError("Invalid editor revision manifest")
                        size = descriptor["bytes"]
                        if type(size) is not int or not 0 < size <= MAX_BUNDLE_FILE:
                            raise RevisionError("Editor revision exceeds bounds")
                        data = artifacts._read(directory, name, size)
                        if len(data) != size or sha(data) != descriptor["sha256"]:
                            raise RevisionError("Editor revision integrity failure")
                        payloads[name] = data
                    snapshot = json.loads(payloads["snapshot.json"])
                    if encode(snapshot) != payloads["snapshot.json"]:
                        raise RevisionError("Invalid editor revision snapshot")
                    export = payloads["export.yaml"].decode("utf-8")
                    if sync:
                        try:
                            for name, expected in {"manifest.json": manifest_raw, **payloads}.items():
                                if artifacts._read(directory, name, len(expected), sync=True) != expected:
                                    raise RevisionError("Editor revision integrity failure")
                            os.fsync(directory)
                            os.fsync(area)
                            parent = artifacts._root(self.path.parent, False)
                            try:
                                os.fsync(parent)
                            finally:
                                os.close(parent)
                        except OSError:
                            raise RevisionUncertain("Editor revision durability uncertain; retry exact request") from None
                    return manifest["receipt"], snapshot, export
                except (ValueError, TypeError, KeyError, RecursionError, OSError):
                    raise RevisionError("Incomplete or corrupt editor revision") from None
        except FileNotFoundError:
            raise KeyError("Editor revision not found") from None
        except (artifacts.ArtifactError, OSError):
            raise RevisionError("Unsafe editor revision bundle") from None

    def read(self, revision_id, sync=False):
        try:
            with self.area(lock=True) as area:
                return self.read_at(area, revision_id, sync)
        except FileNotFoundError:
            raise KeyError("Editor revision not found") from None

    def legacy(self, revision_id):
        """Read historical exports safely, without asserting a durable commit receipt."""
        fd = None
        try:
            fd = artifacts._root(self.path.parent / "editor-revisions", False)
            with artifacts._directory(fd, revision_id) as directory:
                snapshot = json.loads(artifacts._read(directory, "snapshot.json", MAX_BUNDLE_FILE))
                export = artifacts._read(directory, "export.yaml", MAX_BUNDLE_FILE).decode("utf-8")
                if type(snapshot) is not dict:
                    raise RevisionError("Invalid legacy editor snapshot")
                return snapshot, export
        except FileNotFoundError:
            raise KeyError("Revision not found") from None
        except (ValueError, OSError, TypeError, RecursionError):
            raise RevisionError("Unsafe legacy editor revision") from None
        finally:
            if fd is not None:
                os.close(fd)

    def ids(self):
        try:
            with self.area(lock=True) as area:
                result = []
                for revision_id in self._scan(area):
                    with artifacts._directory(area, revision_id) as directory:
                        try:
                            os.stat("manifest.json", dir_fd=directory, follow_symlinks=False)
                        except FileNotFoundError:
                            continue  # Retained incomplete evidence is never a catalogue row.
                        result.append(revision_id)
                return result
        except FileNotFoundError:
            return []

    @staticmethod
    def _scan(area):
        result = []
        with os.scandir(area) as entries:
            for entry in entries:
                if len(result) >= MAX_REVISIONS:
                    raise RevisionError("Editor revision catalogue exceeds bounds")
                if not re.fullmatch("[a-f0-9]{32}", entry.name):
                    raise RevisionError("Invalid editor revision catalogue")
                result.append(entry.name)
        return sorted(result)

    def commit(self, area, revision_id, receipt, snapshot, export):
        if len(self._scan(area)) >= MAX_REVISIONS:
            raise RevisionError("Editor revision catalogue exceeds bounds")
        payloads = {"snapshot.json": encode(snapshot), "export.yaml": export.encode("utf-8")}
        manifest = encode({"schema_version": 1, "receipt": receipt, "files": {
            name: {"bytes": len(data), "sha256": sha(data)} for name, data in payloads.items()
        }})
        if any(len(data) > MAX_BUNDLE_FILE for data in [manifest, *payloads.values()]):
            raise RevisionError("Editor revision exceeds bounds")
        try:
            os.mkdir(revision_id, 0o700, dir_fd=area)
            os.fsync(area)
            with artifacts._directory(area, revision_id) as directory:
                for name, data in payloads.items():
                    artifacts._write(directory, name, data)
                temporary = "commit-" + uuid.uuid4().hex + ".json"
                artifacts._write(directory, temporary, manifest)
                artifacts._rename_noreplace(directory, temporary, directory, "manifest.json")
                os.fsync(directory)
                os.fsync(area)
        except (OSError, artifacts.ArtifactError):
            raise RevisionUncertain("Editor revision commit uncertain; retry exact request") from None
