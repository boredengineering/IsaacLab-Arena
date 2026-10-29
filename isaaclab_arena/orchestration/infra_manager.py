"""Infrastructure lifecycle and health probe manager for Isaac Lab-Arena.

Coordinates multi-service execution (Spec LLM, Visual Critic VLM, and Neo4j Experience Graph)
across host and container boundaries.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
from typing import Any


class InfraManager:
    """Manages service probes and automated startup of Arena infrastructure."""

    DEFAULT_LLM_URL: str = "http://127.0.0.1:8000/v1"
    """Default base URL for Spec Generation LLM."""

    DEFAULT_VLM_URL: str = "http://127.0.0.1:8001/v1"
    """Default base URL for Visual Critic VLM."""

    DEFAULT_NEO4J_URI: str = "bolt://127.0.0.1:7688"
    """Default Bolt URI for Neo4j Experience Graph."""

    def __init__(
        self,
        llm_url: str | None = None,
        vlm_url: str | None = None,
        neo4j_uri: str | None = None,
    ) -> None:
        """Initialize InfraManager with explicit or environment-provided URLs.

        Args:
            llm_url: Base URL for Spec LLM (falls back to ``LOCAL_LLM_BASE_URL`` or default).
            vlm_url: Base URL for Visual VLM (falls back to ``LOCAL_VLM_BASE_URL`` or default).
            neo4j_uri: Bolt URI for Neo4j (falls back to ``NEO4J_URI`` or default).
        """
        self.llm_url = llm_url or os.environ.get("LOCAL_LLM_BASE_URL", self.DEFAULT_LLM_URL)
        self.vlm_url = vlm_url or os.environ.get("LOCAL_VLM_BASE_URL", self.DEFAULT_VLM_URL)
        self.neo4j_uri = neo4j_uri or os.environ.get("NEO4J_URI", self.DEFAULT_NEO4J_URI)

    def is_docker_available(self) -> bool:
        """Check whether the Docker CLI and daemon socket are available in this runtime environment."""
        if shutil.which("docker") is None:
            return False
        try:
            res = subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=3.0,
                check=False,
            )
            return res.returncode == 0
        except Exception:
            return False

    def probe_http_endpoint(self, url: str, timeout: float = 2.0) -> tuple[bool, str, float]:
        """Probe an OpenAI-compatible /v1/models endpoint."""
        base = url.rstrip("/")
        models_url = base if base.endswith("/models") else f"{base}/models"
        req = urllib.request.Request(models_url, method="GET")
        t0 = time.time()
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                elapsed = time.time() - t0
                body = json.loads(resp.read().decode("utf-8"))
                data_list = body.get("data", [])
                model_id = (
                    str(data_list[0].get("id"))
                    if data_list and isinstance(data_list[0], dict) and data_list[0].get("id")
                    else "ok"
                )
                return True, model_id, elapsed
        except Exception as exc:
            return False, str(exc), time.time() - t0

    def probe_neo4j(self, uri: str, timeout: float = 3.0) -> tuple[bool, str, float]:
        """Probe the Neo4j Bolt endpoint with connectivity verification and active query."""
        user = os.environ.get("NEO4J_USER", "neo4j")
        password = os.environ.get("NEO4J_PASSWORD", "isaaclab_arena_password")

        t0 = time.time()
        try:
            import neo4j
        except ImportError:
            return False, "neo4j Python package not installed", time.time() - t0

        try:
            driver = neo4j.GraphDatabase.driver(
                uri,
                auth=(user, password),
                connection_timeout=timeout,
                max_connection_lifetime=timeout,
            )
            driver.verify_connectivity()
            with driver.session() as session:
                res = session.run("RETURN 1 AS probe").single()
                assert res and res["probe"] == 1, "Unexpected probe output"
            driver.close()
            return True, "connected", time.time() - t0
        except Exception as exc:
            return False, str(exc), time.time() - t0

    def probe_all_endpoints(self, timeout: float = 2.0) -> dict[str, dict[str, Any]]:
        """Probe all three services and return structured health results."""
        llm_ok, llm_info, llm_lat = self.probe_http_endpoint(self.llm_url, timeout=timeout)
        vlm_ok, vlm_info, vlm_lat = self.probe_http_endpoint(self.vlm_url, timeout=timeout)
        neo4j_ok, neo4j_info, neo4j_lat = self.probe_neo4j(self.neo4j_uri, timeout=max(timeout, 3.0))

        return {
            "llm": {
                "service": "Spec Generation LLM",
                "endpoint": self.llm_url,
                "ok": llm_ok,
                "info": llm_info,
                "latency_s": round(llm_lat, 3),
            },
            "vlm": {
                "service": "Visual Critic VLM",
                "endpoint": self.vlm_url,
                "ok": vlm_ok,
                "info": vlm_info,
                "latency_s": round(vlm_lat, 3),
            },
            "neo4j": {
                "service": "Neo4j Experience Graph",
                "endpoint": self.neo4j_uri,
                "ok": neo4j_ok,
                "info": neo4j_info,
                "latency_s": round(neo4j_lat, 3),
            },
        }

    def ensure_all_services(self, timeout_s: float = 120.0) -> bool:
        """Verify readiness of all infrastructure services, starting containers if permitted.

        Args:
            timeout_s: Maximum seconds to wait for unready services.

        Returns:
            True if all services are reachable, False otherwise.
        """
        probes = self.probe_all_endpoints(timeout=2.0)
        all_ok = all(p["ok"] for p in probes.values())
        if all_ok:
            return True

        if not self.is_docker_available():
            failed = [f"{p['service']} ({p['endpoint']}): {p['info']}" for p in probes.values() if not p["ok"]]
            print("\n" + "=" * 70, file=sys.stderr)
            print("[ERROR][InfraManager] Service(s) unreachable and Docker daemon is not accessible:", file=sys.stderr)
            for f in failed:
                print(f"  ❌ {f}", file=sys.stderr)
            print("\nPlease execute the following command on the host machine to start the stack:", file=sys.stderr)
            print("  python3 docker/arena_infra.py up", file=sys.stderr)
            print("=" * 70 + "\n", file=sys.stderr, flush=True)
            return False

        # Docker is available; attempt to start stopped containers
        print("[InfraManager] Docker daemon detected; bringing up stopped services...", flush=True)
        container_map = {
            "neo4j": "neo4j-arena",
            "llm": "arena-vllm-spec",
            "vlm": "arena-vllm-visual",
        }
        for key, p in probes.items():
            if not p["ok"]:
                cname = container_map.get(key)
                if cname:
                    print(f"[InfraManager] Starting container '{cname}'...", flush=True)
                    subprocess.run(["docker", "start", cname], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

        # Wait with backoff
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            probes = self.probe_all_endpoints(timeout=2.0)
            if all(p["ok"] for p in probes.values()):
                print("[InfraManager] All infrastructure services verified healthy!", flush=True)
                return True
            time.sleep(2.0)

        unhealthy = [f"{p['service']}: {p['info']}" for p in probes.values() if not p["ok"]]
        print(f"[ERROR][InfraManager] Timed out after {timeout_s}s waiting for services: {unhealthy}", file=sys.stderr)
        return False
