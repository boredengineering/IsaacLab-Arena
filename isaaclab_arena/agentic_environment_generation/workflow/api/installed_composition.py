# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed query/admin composition; never provider or workflow execution authority."""

from contextlib import contextmanager
from pathlib import Path

from .installed_config import MAX_CREDENTIALS, credential_document
from .private_files import Directory, read_private


class PrivateRoles:
    """Explicit private role snapshot; rotation invalidates release, never read authority."""

    def __init__(self, config, *, document=None):
        if config.value["schema_version"] != 3:
            raise ValueError("Explicit private role configuration required")
        self.config = config
        self.document = self._read() if document is None else document
        if self.document["schema_version"] != 2:
            raise ValueError("Versioned private roles required")
        self.protect(config.value)

    def _read(self):
        return credential_document(read_private(self.config.value["credentials_file"], MAX_CREDENTIALS))

    def check_current(self):
        if self._read() != self.document:
            raise ValueError("Private role generation changed; explicit restart and reapproval required")

    @contextmanager
    def release_guard(self):
        """Exclude supported credential rotation throughout the bounded worker send."""
        with Directory(str(Path(self.config.value["credentials_file"]).parent)) as directory:
            with directory.lease("credentials.lock"):
                self.check_current()
                yield

    def protect(self, value):
        from ..provider_configuration import reject_secret

        for item in self.document.get("models", {}).values():
            reject_secret(value, item["api_key"])
        prior = self.document["databases"].get("prior_read")
        if prior:
            reject_secret(value, prior["username"])
            reject_secret(value, prior["password"])

    def model_config(self, role):
        from ..provider_configuration import checked_config

        self.check_current()
        if role not in ("generation", "assessment", "repair"):
            raise ValueError("Unsupported private role")
        selected = self.config.value["role_bindings"][role]
        private = self.document["models"].get(role)
        if private is None or private["alias"] != selected["credential_alias"]:
            raise ValueError("Private model binding unavailable")
        settings = selected["profile"]["settings"]
        result = checked_config(
            dict(
                api_key=private["api_key"],
                model=settings["model"],
                base_url=settings["endpoint"],
                inference_profile=settings["inference_policy"],
            )
        )
        if "workflow_accounting" in settings:
            result["workflow_accounting"] = settings["workflow_accounting"]
        if "request_bounds" in settings:
            result["request_bounds"] = settings["request_bounds"]
        return result

    def prior_read(self):
        """Return only the explicitly configured prior login; never open a driver."""
        self.check_current()
        selected = self.config.value["role_bindings"]["prior_read"]
        private = self.document["databases"].get("prior_read")
        if private is None or private["alias"] != selected["credential_alias"]:
            raise ValueError("Private prior binding unavailable")
        return {**selected, **private}

    def prior_source(self, selection, *, credentials=False):
        """Check exact public selection; load the separate login only for an authorized read."""
        selected = self.config.value["role_bindings"]["prior_read"]
        if any(getattr(selection, key) != selected[key] for key in ("endpoint", "database", "credential_alias")):
            raise ValueError("Selected prior source differs from installed binding")
        if not credentials:
            return None
        from isaaclab_arena_examples.agentic_environment_generation.web_api.graph_access import checked_graph_config

        private = self.prior_read()
        return checked_graph_config(
            dict(
                uri=selected["endpoint"],
                database=selected["database"],
                user=private["username"],
                password=private["password"],
            )
        )


class Authority:
    def __init__(self, config):
        self.admin = config.value["bootstrap_principal"]
        self.reader = config.value["read_principal"]

    def require_admin(self, principal):
        if principal != self.admin:
            raise PermissionError("Administrative principal required")

    def require_read(self, principal):
        if principal != self.reader:
            raise PermissionError("Read principal required")


class Resources:
    """Load only the selected explicit local credentials, with fixed basic auth."""

    def __init__(self, config):
        self.config = config
        self.authority = Authority(config)
        document = credential_document(read_private(config.value["credentials_file"], MAX_CREDENTIALS))
        self.credential = document["databases"]["operational"]
        self.roles = PrivateRoles(config, document=document) if config.value["schema_version"] == 3 else None

    def protect(self, value):
        def walk(item):
            if isinstance(item, str):
                if any(self.credential[key] in item for key in ("username", "password")):
                    raise PermissionError("Public value rejected")
            elif isinstance(item, dict):
                for key, child in item.items():
                    walk(key)
                    walk(child)
            elif isinstance(item, (list, tuple)):
                for child in item:
                    walk(child)

        walk(value)
        if self.roles is not None:
            self.roles.protect(value)

    def private_roles(self):
        if self.roles is None:
            raise ValueError("Explicit private roles required")
        return self.roles

    def driver(self):
        from neo4j import GraphDatabase, basic_auth

        return GraphDatabase.driver(
            self.config.value["bolt_uri"],
            auth=basic_auth(self.credential["username"], self.credential["password"]),
            connection_timeout=2,
            connection_acquisition_timeout=3,
            max_transaction_retry_time=0,
            max_connection_pool_size=4,
        )

    def store(self, driver):
        from ..neo4j_store import Neo4jWorkflowStore

        binding = self.config.binding
        return Neo4jWorkflowStore(
            driver, database=binding.database, deployment_id=binding.deployment_id, workspace_id=binding.workspace_id
        )


def administer(config, action, *, create=False, registration_path=None):
    from neo4j import Query

    from ..admin import WorkflowScopeAdmin

    resources = Resources(config)
    resources.authority.require_admin(config.value["bootstrap_principal"])
    with resources.driver() as driver:
        store = resources.store(driver)
        admin = WorkflowScopeAdmin(store, resources.authority)
        if action == "initialize-schema":
            with driver.session(database=config.binding.database) as session:
                for statement in store.schema_requirements():
                    session.run(Query(statement, timeout=5)).consume()
                session.run(Query("CALL db.awaitIndexes(30)", timeout=35)).consume()
            store.verify_schema()
        elif action == "initialize-scope":
            admin.initialize_scope(resources.authority.admin, config.binding, protect=resources.protect)
        elif action == "initialize-artifacts":
            admin.initialize_artifacts(
                resources.authority.admin,
                config.binding,
                root=Path(config.value["artifact_root"]),
                create=create,
                protect=resources.protect,
            )
        elif action == "register-profile":
            from ..profiles import MAX_PROFILE_BYTES, ProfileRegistration
            from ..service import WorkflowProfileAdmin
            from .private_files import decode, encode

            raw = read_private(registration_path, MAX_PROFILE_BYTES)
            registration = ProfileRegistration.model_validate_json(encode(decode(raw, MAX_PROFILE_BYTES)))
            WorkflowProfileAdmin(store, resources.authority).register_profile(
                resources.authority.admin, registration, protect=resources.protect
            )
        else:
            raise ValueError("Unsupported administrative command")
    return {"schema_version": 1, "code": "admin_complete"}
