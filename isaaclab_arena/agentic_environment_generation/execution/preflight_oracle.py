# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Job J1: Fast CPU preflight service triad oracle (ports 8000, 8001, 7688).

Must never import control-plane workflow modules, Omniverse Kit, or PyTorch.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PreflightTriadStatus:
    """Result of probing the local LLM, VLM, and Neo4j service triad."""

    llm_ok: bool
    llm_info: str
    llm_url: str
    vlm_ok: bool
    vlm_info: str
    vlm_url: str
    neo4j_ok: bool
    neo4j_info: str
    neo4j_uri: str
    elapsed_ms: float

    @property
    def all_ok(self) -> bool:
        """Return True when all three local endpoints responded healthy."""
        return self.llm_ok and self.vlm_ok and self.neo4j_ok

    def to_dict(self) -> dict[str, Any]:
        """Serialize preflight status to a JSON-compatible dictionary."""
        return {
            "all_ok": self.all_ok,
            "llm": {"ok": self.llm_ok, "info": self.llm_info, "url": self.llm_url},
            "vlm": {"ok": self.vlm_ok, "info": self.vlm_info, "url": self.vlm_url},
            "neo4j": {"ok": self.neo4j_ok, "info": self.neo4j_info, "uri": self.neo4j_uri},
            "elapsed_ms": round(self.elapsed_ms, 3),
        }


def verify_service_endpoint(url: str, timeout: float = 2.0) -> tuple[bool, str]:
    """Verify that an OpenAI-compatible service endpoint responds to GET /v1/models.

    Args:
        url: Base URL of the OpenAI-compatible service (e.g. ``http://127.0.0.1:8000/v1``).
        timeout: Socket timeout in seconds.

    Returns:
        Tuple of ``(reachable, model_id_or_error)``.
    """
    base = url.rstrip("/")
    models_url = base if base.endswith("/models") else f"{base}/models"
    req = urllib.request.Request(models_url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = json.loads(resp.read().decode("utf-8"))
            data_list = body.get("data", [])
            model_id = (
                str(data_list[0].get("id"))
                if data_list and isinstance(data_list[0], dict) and data_list[0].get("id")
                else "ok"
            )
            return True, model_id
    except Exception as exc:
        return False, f"Endpoint {models_url} unreachable: {exc}"


def verify_neo4j_endpoint(
    uri: str | None = None,
    user: str | None = None,
    password: str | None = None,
    timeout: float = 3.0,
) -> tuple[bool, str]:
    """Verify that the Neo4j Graph database endpoint responds to Bolt handshake and query.

    Args:
        uri: Bolt URI (defaults to ``NEO4J_URI`` or ``bolt://127.0.0.1:7688``).
        user: Username (defaults to ``NEO4J_USER`` or ``neo4j``).
        password: Password (defaults to ``NEO4J_PASSWORD`` or ``isaaclab_arena_password``).
        timeout: Connection timeout in seconds.

    Returns:
        Tuple of ``(reachable, message)``.
    """
    uri = uri or os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688")
    user = user or os.environ.get("NEO4J_USER", "neo4j")
    password = password or os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")

    try:
        import neo4j
    except ImportError:
        return False, "neo4j Python package is not installed"

    try:
        driver = neo4j.GraphDatabase.driver(
            uri,
            auth=(user, password),
            connection_timeout=timeout,
            max_connection_lifetime=timeout,
        )
        driver.verify_connectivity()
        with driver.session() as session:
            result = session.run("RETURN 1 AS probe").single()
            if not result or result["probe"] != 1:
                driver.close()
                return False, f"Unexpected probe result from Neo4j at {uri}"
        driver.close()
        return True, "connected"
    except Exception as exc:
        return False, f"Neo4j endpoint {uri} unreachable: {exc}"


def probe_service_triad(
    *,
    llm_url: str | None = None,
    vlm_url: str | None = None,
    neo4j_uri: str | None = None,
    timeout: float = 2.0,
) -> PreflightTriadStatus:
    """Probe the local LLM (8000), VLM (8001), and Neo4j (7688) endpoints on CPU.

    Args:
        llm_url: Optional override for the Spec LLM endpoint.
        vlm_url: Optional override for the Visual VLM endpoint.
        neo4j_uri: Optional override for the Neo4j Bolt URI.
        timeout: Per-endpoint probe timeout in seconds.

    Returns:
        Structured ``PreflightTriadStatus`` with reachability and timing.
    """
    t0 = time.perf_counter()
    resolved_llm = llm_url or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    resolved_vlm = vlm_url or os.environ.get("LOCAL_VLM_BASE_URL", "http://127.0.0.1:8001/v1")
    resolved_neo4j = neo4j_uri or os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688")

    llm_ok, llm_info = verify_service_endpoint(resolved_llm, timeout=timeout)
    vlm_ok, vlm_info = verify_service_endpoint(resolved_vlm, timeout=timeout)
    neo4j_ok, neo4j_info = verify_neo4j_endpoint(resolved_neo4j, timeout=timeout)
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    return PreflightTriadStatus(
        llm_ok=llm_ok,
        llm_info=llm_info,
        llm_url=resolved_llm,
        vlm_ok=vlm_ok,
        vlm_info=vlm_info,
        vlm_url=resolved_vlm,
        neo4j_ok=neo4j_ok,
        neo4j_info=neo4j_info,
        neo4j_uri=resolved_neo4j,
        elapsed_ms=elapsed_ms,
    )


def check_preflight_service_triad(args_cli: argparse.Namespace) -> PreflightTriadStatus | None:
    """Pre-flight check the full infrastructure triad (Spec LLM, Visual VLM, Neo4j) before simulation starts."""
    if getattr(args_cli, "mode", None) in ("schema", "catalog"):
        return None

    if getattr(args_cli, "ensure_infra", False):
        try:
            from isaaclab_arena.orchestration.infra_manager import InfraManager

            infra_mgr = InfraManager()
            infra_mgr.ensure_all_services()
        except Exception as exc:
            print(f"[WARNING][InfraManager] Auto-ensure infra encountered an issue: {exc}", flush=True)

    is_generation_mode = getattr(args_cli, "mode", None) in ("resolve", "grounded-resolve", "grounded_resolve", "full")
    is_permissive = getattr(args_cli, "permissive", False)
    is_strict = getattr(args_cli, "strict_critics", False) or (is_generation_mode and not is_permissive)

    llm_url = getattr(args_cli, "base_url", None) or os.environ.get("LOCAL_LLM_BASE_URL", "http://127.0.0.1:8000/v1")
    vlm_url = os.environ.get("LOCAL_VLM_BASE_URL", "http://127.0.0.1:8001/v1")
    neo4j_uri = os.environ.get("NEO4J_URI", "bolt://127.0.0.1:7688")

    status = probe_service_triad(llm_url=llm_url, vlm_url=vlm_url, neo4j_uri=neo4j_uri, timeout=2.0)

    if is_strict:
        failed_services = []
        if not status.llm_ok:
            failed_services.append(f"Spec LLM ({status.llm_url}): {status.llm_info}")
        if getattr(args_cli, "mode", None) in ("grounded-resolve", "grounded_resolve", "full") and not status.vlm_ok:
            failed_services.append(f"Visual VLM ({status.vlm_url}): {status.vlm_info}")
        if not status.neo4j_ok:
            failed_services.append(f"Neo4j Experience Graph ({status.neo4j_uri}): {status.neo4j_info}")

        if failed_services:
            print("\n" + "=" * 70, file=sys.stderr)
            print("[ERROR][Preflight] Required infrastructure service(s) failed health check:", file=sys.stderr)
            for fail_msg in failed_services:
                print(f"  ❌ {fail_msg}", file=sys.stderr)
            print("\nTo start or verify all services on the host system, run:", file=sys.stderr)
            print("  python3 docker/arena_infra.py up", file=sys.stderr)
            print("To intentionally run offline without services, re-run with --permissive.", file=sys.stderr)
            print("=" * 70 + "\n", file=sys.stderr, flush=True)
            sys.exit(2)
    else:
        if not status.llm_ok:
            print(
                f"[WARNING] LLM service endpoint {status.llm_url} unreachable ({status.llm_info}); using fallback.",
                flush=True,
            )
        if not status.vlm_ok:
            print(
                f"[WARNING] VLM service endpoint {status.vlm_url} unreachable ({status.vlm_info}); "
                "using Tier 3 geometric fallback.",
                flush=True,
            )
        if not status.neo4j_ok:
            print(
                f"[WARNING] Neo4j endpoint {status.neo4j_uri} unreachable ({status.neo4j_info}); "
                "proceeding without graph sync.",
                flush=True,
            )
    return status


class PreflightOracleWorker:
    """Boundary worker for Job J1: CPU-only preflight triad health oracle."""

    def __init__(
        self,
        *,
        llm_url: str | None = None,
        vlm_url: str | None = None,
        neo4j_uri: str | None = None,
        timeout: float = 2.0,
    ) -> None:
        self.llm_url = llm_url
        self.vlm_url = vlm_url
        self.neo4j_uri = neo4j_uri
        self.timeout = timeout

    def probe(self) -> PreflightTriadStatus:
        """Execute a fast CPU preflight probe of the local service triad."""
        return probe_service_triad(
            llm_url=self.llm_url,
            vlm_url=self.vlm_url,
            neo4j_uri=self.neo4j_uri,
            timeout=self.timeout,
        )
