# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Private graph connection configuration for explicitly authorized retrieval."""

import os
import time
from contextlib import nullcontext
from urllib.parse import urlsplit

from isaaclab_arena.agentic_environment_generation.graph_cleanup import GraphCleanupError, close_graph_resources

from .provider_security import reject_secret


def checked_graph_config(config):
    """Validate a private graph profile."""
    if not isinstance(config, dict) or set(config) != {"uri", "user", "password", "database"}:
        raise ValueError("Invalid graph configuration")
    limits = {"uri": 2048, "user": 256, "password": 4096, "database": 256}
    for name, limit in limits.items():
        value = config[name]
        if (
            not isinstance(value, str)
            or not 1 <= len(value.encode("utf-8")) <= limit
            or any(ord(c) < 32 for c in value)
            or (name == "database" and not value.strip())
        ):
            raise ValueError("Invalid graph configuration")
    try:
        uri = urlsplit(config["uri"])
        port = uri.port
        if (
            uri.scheme not in {"bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc"}
            or not uri.hostname
            or uri.username is not None
            or uri.password is not None
            or uri.path not in {"", "/"}
            or uri.query
            or uri.fragment
            or any(c.isspace() for c in config["uri"])
            or port == 0
        ):
            raise ValueError("Invalid graph configuration")
        reject_secret({key: config[key] for key in ("uri", "user", "database")}, config["password"])
    except ValueError:
        raise ValueError("Invalid graph configuration") from None
    return dict(config)


def configuration():
    """Read explicit server graph configuration without probing its destination."""
    config = {
        "uri": os.environ.get("NEO4J_URI"),
        "user": os.environ.get("NEO4J_USER"),
        "password": os.environ.get("NEO4J_PASSWORD"),
        "database": os.environ.get("NEO4J_DATABASE", "neo4j"),
    }
    try:
        return checked_graph_config(config)
    except ValueError:
        return None


def retrieve_snapshot(prompt, config, *, driver_factory=None, managed_context=None, settings=None, read_guard=None):
    """Retrieve through an explicitly configured, owned and bounded driver."""
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    retriever_options = {}
    driver_limits = dict(
        connection_timeout_seconds=3, connection_acquisition_timeout_seconds=5, max_transaction_retry_time_seconds=0
    )
    if settings is not None:
        from isaaclab_arena.agentic_environment_generation.workflow.contracts import PriorRetrievalSettings

        settings = PriorRetrievalSettings.model_validate(settings.model_dump(mode="json"))
        retriever_options = {key: getattr(settings, key) for key in ("limit", "min_success_rate", "min_episodes")}
        driver_limits = {key: getattr(settings, key) for key in driver_limits}
    managed_open = None
    cleanup_errors: tuple[type[BaseException], ...] = (GraphCleanupError,)
    if managed_context is not None:
        if config is None:
            raise ValueError("Managed retrieval requires graph authorization")
        from .managed_retrieval import ReadCleanupError, checked_context, open_managed_provider

        managed_open = open_managed_provider
        cleanup_errors += (ReadCleanupError,)
        managed_context = checked_context(managed_context, checked_graph_config(config))
    unavailable = GraphRAGRetriever().retrieve_prior_snapshot(prompt, **retriever_options)
    denied = False

    def check(seconds=0.0):
        nonlocal denied
        if denied:
            raise ValueError("Prior read authorization unavailable")
        if read_guard is not None:
            try:
                read_guard(seconds)
            except Exception:
                denied = True
                raise ValueError("Prior read authorization unavailable") from None

    def before_read():
        check(
            driver_limits["connection_timeout_seconds"]
            + driver_limits["connection_acquisition_timeout_seconds"]
            + unavailable["effective_settings"]["query_timeout_seconds"]
        )

    if config is None:
        check()
        return unavailable
    config = checked_graph_config(config)
    unavailable["effective_settings"].update(driver_limits)
    started = time.monotonic()
    driver = None
    try:
        before_read()
        driver = (driver_factory or get_neo4j_driver)(
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            connection_timeout=driver_limits["connection_timeout_seconds"],
            connection_acquisition_timeout=driver_limits["connection_acquisition_timeout_seconds"],
            max_connection_pool_size=1,
            max_transaction_retry_time=driver_limits["max_transaction_retry_time_seconds"],
        )

        attachment = nullcontext(None)
        if managed_context is not None:
            assert managed_open is not None, "Explicit managed attachment required"
            attachment = managed_open(managed_context)
        with attachment as provider:
            snapshot = GraphRAGRetriever(driver).retrieve_prior_snapshot(
                prompt,
                database=config["database"],
                managed_selection_provider=provider,
                before_read=before_read if read_guard is not None else None,
                **retriever_options,
            )
        check()
        snapshot["effective_settings"].update(driver_limits)
        reject_secret(snapshot, config["password"])
        return snapshot
    except cleanup_errors:
        raise
    except Exception:
        unavailable["warnings"] = ["retrieval_failed"]
        unavailable["timing"] = {"source": "local_monotonic", "elapsed_seconds": time.monotonic() - started}
        return unavailable
    finally:
        close_graph_resources(driver)
        check()
