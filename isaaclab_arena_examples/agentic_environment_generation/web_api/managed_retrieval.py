# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Child-only existing-store reads; never initialize or recover a Journal.

SQLite mode=ro observes authoritative WAL and may maintain WAL/SHM bookkeeping.
This is an authorized local read, not source-preserving offline administration.
The caller owns the private reference authority; no graph-derived paths are used.

Server opt-in: create_app(..., managed_retrieval_enabled=True,
research_roots={store_id: absolute_root}, publication_profiles=operator_profiles).
Publication execution need not be enabled. Stores and publication evidence must
already exist in this API state's journal; attachment cannot create them. Graph
read credentials remain the separately authorized NEO4J_URI/USER/PASSWORD/DATABASE
profile. Only immutable publication profiles with the exact same URI and database
contribute targets; the writer's user contributes its existing public revision,
but writer credentials never enter the child envelope. No HTTP reference intake
or automatic filesystem/graph discovery is provided.

The accepted retrieval grant binds a SHA256 of <=32 KiB of references (<=16 stores
and targets); parent and worker check it within the existing 512-KiB envelope.
Refine and grants captured without managed configuration retain their old paths.
Source attachment and all graph readback run in the owned generation child. Local
store opens may inspect existing artifact trees; the outer worker deadline owns
hard cancellation. These operator-owned paths are not a sandbox against another
process running as the same OS user. Immutable publication readback does not make
mutable evaluation evidence a database snapshot.
"""

import os
import sqlite3
import stat
import threading
from contextlib import ExitStack, contextmanager
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.workbench.journal import Journal
from isaaclab_arena.agentic_environment_generation.workbench.research_publication import PublicationAttempts
from isaaclab_arena.agentic_environment_generation.workbench.research_retrieval import ManagedSelectionProvider
from isaaclab_arena.agentic_environment_generation.workbench.research_store import ResearchStore


class ReadCleanupError(ValueError):
    """An owned read handle did not acknowledge cleanup."""


def _close(handle):
    try:
        handle.close()
    except Exception:
        raise ReadCleanupError("Managed retrieval cleanup failed") from None


class ExistingJournalReader:
    """Expose only the registry's read interface, not Journal lifecycle or transactions."""

    _check_schema = Journal._check_schema

    def __init__(self, path):
        path = Path(path)
        for ancestor in path.parents:
            if ancestor.is_symlink():
                raise ValueError("Managed journal path must not contain symlinks")
        for candidate in (path, Path(str(path) + "-wal"), Path(str(path) + "-shm")):
            try:
                info = candidate.lstat()
            except FileNotFoundError:
                if candidate == path:
                    raise ValueError("Managed journal must already exist") from None
                continue
            if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_nlink != 1:
                raise ValueError("Managed journal must be an owned regular file")
        self._lock = threading.RLock()
        self.db = sqlite3.connect(Path(path).as_uri() + "?mode=ro", uri=True, timeout=1)
        self.db.row_factory = sqlite3.Row
        try:
            self.db.execute("PRAGMA query_only=ON")
            self.db.set_authorizer(self._authorize)
            self._check_schema()
        except BaseException:
            self.db.close()
            raise

    @staticmethod
    def _authorize(action, arg1, arg2, database, source):
        if action in (sqlite3.SQLITE_SELECT, sqlite3.SQLITE_READ, sqlite3.SQLITE_FUNCTION):
            return sqlite3.SQLITE_OK
        if action == sqlite3.SQLITE_PRAGMA and arg1 in {"user_version", "table_info"}:
            if arg1 == "table_info" or arg2 is None:
                return sqlite3.SQLITE_OK
        return sqlite3.SQLITE_DENY

    def close(self):
        self.db.close()


@contextmanager
def open_managed_provider(context):
    """Attach exact existing store/registry identities and close every owned handle."""
    context = checked_context(context)
    with ExitStack() as stack:
        reader = ExistingJournalReader(context["journal_path"])
        stack.callback(_close, reader)
        pairs = []
        for reference in context["stores"]:
            store = ResearchStore.open(
                reader, reference["root"], reference["store_id"], protect_public=lambda value: None
            )
            stack.callback(_close, store)
            if store.registry.registry_id != context["registry_id"]:
                raise ValueError("Managed registry identity mismatch")
            attempts = PublicationAttempts(reader, store.registry, initialize=False)
            pairs.append((store, attempts))
        yield ManagedSelectionProvider(
            pairs, database=context["graph"]["database"], authorized_targets=context["authorized_targets"]
        )


def configured_enabled(enabled, roots, profiles):
    """Require an explicit boolean opt-in and nonempty operator configuration."""
    if type(enabled) is not bool:
        raise ValueError("Invalid managed retrieval enable flag")
    if enabled and (not roots or not profiles):
        raise ValueError("Managed retrieval requires configured stores and profiles")
    return enabled


def configured_context(journal_path, journal, roots, profiles, graph):
    """Bind operator roots and attested targets to the authorized endpoint/database."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import ResearchRegistry

    from .execution_grants import _bounded_copy
    from .graph_access import checked_graph_config
    from .publication_authorization import PublicationAuthorization
    from .research_profiles import configured_publication_profiles, configured_research_roots

    graph = checked_graph_config(graph)
    roots = configured_research_roots(roots)
    profiles = configured_publication_profiles(profiles)
    if not 1 <= len(roots) <= 16:
        raise ValueError("Managed retrieval requires explicit bounded stores")
    authority = PublicationAuthorization(None, lambda: profiles)
    targets = {
        key: authority.profile_metadata(key)
        for key, profile in profiles.items()
        if all(profile["connection"][field] == graph[field] for field in ("uri", "database"))
    }
    if not targets:
        raise ValueError("Managed retrieval requires a matching immutable publication profile")
    registry = ResearchRegistry(journal, initialize=False)
    value = _bounded_copy(
        {
            "schema_version": 1,
            "journal_path": str(journal_path),
            "registry_id": registry.registry_id,
            "stores": [{"store_id": key, "root": str(root)} for key, root in sorted(roots.items())],
            "authorized_targets": targets,
            "graph": {key: graph[key] for key in ("uri", "database")},
        },
        max_bytes=32768,
    )
    from .provider_security import reject_secret

    authority.protect_public(value)
    reject_secret(value, graph["password"])
    return checked_context(value, graph)


def context_digest(context):
    """Bind only private references, never catalogues or writer credentials."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import digest

    return digest(context)


def checked_context(value, graph=None):
    """Detach at most 32 KiB of strict private references; no filesystem or graph IO."""
    from isaaclab_arena.agentic_environment_generation.workbench.research_registry import checked_identifier

    from .execution_grants import _bounded_copy
    from .research_profiles import configured_research_roots

    try:
        value = _bounded_copy(value, max_bytes=32768)
        if (
            type(value) is not dict
            or set(value) != {"schema_version", "journal_path", "registry_id", "stores", "authorized_targets", "graph"}
            or type(value["schema_version"]) is not int
            or value["schema_version"] != 1
        ):
            raise ValueError
        checked_identifier(value["registry_id"])
        configured_research_roots({"journal": value["journal_path"]})
        refs = value["stores"]
        if type(refs) is not list or not 1 <= len(refs) <= 16:
            raise ValueError
        roots = {}
        for ref in refs:
            if type(ref) is not dict or set(ref) != {"store_id", "root"} or ref["store_id"] in roots:
                raise ValueError
            roots[checked_identifier(ref["store_id"])] = ref["root"]
        configured_research_roots(roots)
        targets = value["authorized_targets"]
        if type(targets) is not dict or not 1 <= len(targets) <= 16:
            raise ValueError
        for key, target in targets.items():
            checked_identifier(key)
            if (
                type(target) is not dict
                or set(target) != {"profile_id", "revision", "scope_ownership"}
                or (
                    target["profile_id"] != key
                    or target["scope_ownership"] != "cooperative_immutable"
                    or type(target["revision"]) is not str
                    or len(target["revision"]) != 64
                    or any(c not in "0123456789abcdef" for c in target["revision"])
                )
            ):
                raise ValueError
        connection = value["graph"]
        if type(connection) is not dict or set(connection) != {"uri", "database"}:
            raise ValueError
        if graph is not None and connection != {key: graph[key] for key in ("uri", "database")}:
            raise ValueError
        from .graph_access import checked_graph_config

        checked_graph_config({**connection, "user": "reader", "password": "context-validation-only"})
        return value
    except Exception:
        raise ValueError("Invalid private managed retrieval context") from None


def private_context(inputs, private):
    """Require the exact accepted grant digest before either private-pipe boundary."""
    try:
        metadata = inputs.get("workflow_authorization") or {}
        grant = metadata.get("retrieval") or {}
        expected = (grant.get("profile") or {}).get("managed_context_sha256")
        if expected is None:
            if "managed_context" in private:
                raise ValueError
            return None
        if inputs.get("operation") != "new" or private.get("graph_config") is None:
            raise ValueError
        value = checked_context(private["managed_context"], private["graph_config"])
        from .provider_security import reject_secret

        reject_secret(value, (private.get("config") or {}).get("api_key"))
        reject_secret(value, private["graph_config"].get("password"))
        if context_digest(value) != expected:
            raise ValueError
        return value
    except Exception:
        raise ValueError("Invalid private managed retrieval authorization") from None
