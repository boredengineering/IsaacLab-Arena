# Copyright (c) 2026, The Isaac Lab Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
"""Fixed query/admin composition; never provider or workflow execution authority."""

from pathlib import Path

from .installed_config import MAX_CREDENTIALS, credential_document
from .private_files import read_private


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
        self.credential = credential_document(read_private(config.value["credentials_file"], MAX_CREDENTIALS))[
            "databases"
        ]["operational"]

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
