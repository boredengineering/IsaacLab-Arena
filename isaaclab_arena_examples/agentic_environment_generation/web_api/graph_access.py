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


def retrieve_snapshot(prompt, config, *, driver_factory=None, managed_context=None):
    """Retrieve through an explicitly configured, owned and bounded driver."""
    from isaaclab_arena.agentic_environment_generation.graph_rag import GraphRAGRetriever
    from isaaclab_arena.agentic_environment_generation.lpg_neo4j_sync import get_neo4j_driver

    if managed_context is not None:
        from .managed_retrieval import checked_context

        if config is None:
            raise ValueError("Managed retrieval requires graph authorization")
        managed_context = checked_context(managed_context, checked_graph_config(config))
    unavailable = GraphRAGRetriever().retrieve_prior_snapshot(prompt)
    if config is None:
        return unavailable
    config = checked_graph_config(config)
    unavailable["effective_settings"].update(
        connection_timeout_seconds=3,
        connection_acquisition_timeout_seconds=5,
        max_transaction_retry_time_seconds=0,
    )
    from .managed_retrieval import ReadCleanupError, open_managed_provider

    started = time.monotonic()
    driver = None
    try:
        driver = (driver_factory or get_neo4j_driver)(
            uri=config["uri"],
            user=config["user"],
            password=config["password"],
            connection_timeout=3,
            connection_acquisition_timeout=5,
            max_connection_pool_size=1,
            max_transaction_retry_time=0,
        )

        attachment = nullcontext(None) if managed_context is None else open_managed_provider(managed_context)
        with attachment as provider:
            snapshot = GraphRAGRetriever(driver).retrieve_prior_snapshot(
                prompt, database=config["database"], managed_selection_provider=provider
            )
        snapshot["effective_settings"].update(
            connection_timeout_seconds=3,
            connection_acquisition_timeout_seconds=5,
            max_transaction_retry_time_seconds=0,
        )
        reject_secret(snapshot, config["password"])
        return snapshot
    except (ReadCleanupError, GraphCleanupError):
        raise
    except Exception:
        unavailable["warnings"] = ["retrieval_failed"]
        unavailable["timing"] = {"source": "local_monotonic", "elapsed_seconds": time.monotonic() - started}
        return unavailable
    finally:
        close_graph_resources(driver)
