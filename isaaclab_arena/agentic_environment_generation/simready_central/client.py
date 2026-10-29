# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Client for discovering, downloading, and inspecting SimReady Central assets."""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SIMREADY_CENTRAL_API_BASE = "https://nvidia-simready-central.hf.space"
SIMREADY_GITHUB_RAW_BASE = "https://raw.githubusercontent.com/NVIDIA-Omniverse/simready-central/main"
DEFAULT_CACHE_DIR = Path("artifacts/assets/simready")


@dataclass
class SimReadyAssetHit:
    """A search hit returned by SimReady Central."""

    id: str
    name: str
    path: str
    score: float
    download_url: str | None = None
    manifest_url: str | None = None
    dataset_id: str = "nvidia/simready-assets"
    category: str | None = None
    usd_properties: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert hit to dictionary."""
        return asdict(self)


class SimReadyCentralClient:
    """Client for NVIDIA SimReady Central DeepSearch API and OEM Asset Catalogs."""

    def __init__(
        self,
        api_base: str = SIMREADY_CENTRAL_API_BASE,
        github_raw_base: str = SIMREADY_GITHUB_RAW_BASE,
        cache_dir: Path | str = DEFAULT_CACHE_DIR,
        timeout_s: float = 15.0,
    ):
        """Initialize the client.

        Args:
            api_base: Base URL for SimReady Central DeepSearch REST API.
            github_raw_base: Base URL for raw GitHub submissions repository.
            cache_dir: Directory where downloaded assets are stored.
            timeout_s: HTTP request timeout in seconds.
        """
        self.api_base = api_base.rstrip("/")
        self.github_raw_base = github_raw_base.rstrip("/")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s

    def check_health(self) -> dict[str, Any]:
        """Check the operational health of SimReady Central DeepSearch API.

        Returns:
            Dict containing health code and status description.
        """
        url = f"{self.api_base}/health"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            return {"status": "unreachable", "error": str(e), "url": url}

    def search_hybrid(
        self,
        query: str,
        limit: int = 10,
        category: str | None = None,
        min_bbox: list[float] | None = None,
        max_bbox: list[float] | None = None,
    ) -> list[SimReadyAssetHit]:
        """Execute hybrid search on SimReady Central with text and SigLIP2 vectors.

        Args:
            query: Natural language search string (e.g. 'office desk drawer', 'microwave').
            limit: Maximum number of results to return.
            category: Optional semantic category filter.
            min_bbox: Optional [min_x, min_y, min_z] bounding box filter.
            max_bbox: Optional [max_x, max_y, max_z] bounding box filter.

        Returns:
            List of SimReadyAssetHit records.
        """
        url = f"{self.api_base}/search_hybrid"
        payload: dict[str, Any] = {
            "hybrid_text_query": query,
            "vector_queries": [
                {
                    "field_name": "siglip2-embedding.embedding",
                    "query_type": "text",
                    "query": query,
                }
            ],
            "file_extension_include": "usd*",
            "return_metadata": True,
            "return_usd_properties": True,
            "return_usd_dimensions": True,
            "limit": limit,
        }

        if category:
            payload["filter_by_properties"] = f"class={category}"
        if min_bbox and len(min_bbox) >= 2:
            payload["min_bbox_x"] = min_bbox[0]
            payload["min_bbox_y"] = min_bbox[1]
        if max_bbox and len(max_bbox) >= 2:
            payload["max_bbox_x"] = max_bbox[0]
            payload["max_bbox_y"] = max_bbox[1]

        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        )

        hits: list[SimReadyAssetHit] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                res = json.loads(resp.read().decode())
                raw_hits = res.get("hits", res.get("results", []))
                for h in raw_hits:
                    hit_id = h.get("id", "")
                    score = float(h.get("score", 0.0))
                    src = h.get("source", {})
                    name = src.get("name") or hit_id
                    raw_path = src.get("path") or ""

                    # Parse Hugging Face dataset URL
                    # e.g.: hf://huggingface.co/datasets/nvidia/simready-assets/resolve/<sha>/desk_a01/simready_usd/sm_desk_a01_01.usd
                    download_url = None
                    manifest_url = None
                    if "datasets/" in raw_path:
                        parts = raw_path.split("datasets/")[-1]
                        # Reconstruct HTTPS resolve URL
                        download_url = f"https://huggingface.co/datasets/{parts}"
                        # Compute packaging manifest URL
                        folder_match = re.search(r"/([^/]+)/simready_usd/", download_url)
                        if folder_match:
                            asset_folder = folder_match.group(1)
                            manifest_url = re.sub(
                                r"/([^/]+)/simready_usd/.*$",
                                f"/{asset_folder}/com.nvidia.simready.packaging.json",
                                download_url,
                            )

                    hits.append(
                        SimReadyAssetHit(
                            id=hit_id,
                            name=name,
                            path=raw_path,
                            score=score,
                            download_url=download_url,
                            manifest_url=manifest_url,
                            usd_properties=h.get("usd_properties", {}),
                            dimensions=h.get("dimensions", {}),
                        )
                    )
        except Exception as e:
            # Fall back to GitHub submission text matching across primary OEMs if search service has transient errors
            all_hits: list[SimReadyAssetHit] = []
            for oem_ns in ("nvidia", "ForgeCAD", "PalatialSim"):
                all_hits.extend(self.search_oem_catalog(query=query, oem=oem_ns, limit=limit))
            all_hits.sort(key=lambda item: item.score, reverse=True)
            hits = all_hits[:limit]

        return hits

    def list_oem_organizations(self) -> list[str]:
        """List known OEM and creator namespaces submitting to SimReady Central."""
        return [
            "nvidia",
            "frankarobotics",
            "Robotiq-Official",
            "FANUC-CORPORATION",
            "Comau",
            "AGIBOT-Yuanzheng",
            "onrobot",
            "standardbots",
            "LGElectronics",
            "TeradyneRobotics",
            "ForgeCAD",
            "PalatialSim",
            "Menlo",
            "Vertiv",
        ]

    def get_oem_submissions(self, oem: str = "nvidia") -> list[str]:
        """Fetch verified submission manifest URLs for a given OEM namespace.

        Args:
            oem: Organization name under submissions/ (e.g. 'nvidia', 'frankarobotics').

        Returns:
            List of Hugging Face package manifest URLs.
        """
        url = f"{self.github_raw_base}/submissions/{oem}/simready-assets"
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                lines = resp.read().decode().splitlines()
                return [line.strip() for line in lines if line.strip() and not line.startswith("#")]
        except Exception as e:
            return []

    def search_oem_catalog(self, query: str, oem: str = "nvidia", limit: int = 10) -> list[SimReadyAssetHit]:
        """Search the OEM submission catalog text manifest for matching assets.

        Args:
            query: Substring keyword (e.g. 'desk', 'microwave', 'fr3', 'robotiq').
            oem: Organization name.
            limit: Maximum hits.

        Returns:
            List of SimReadyAssetHit records.
        """
        urls = self.get_oem_submissions(oem=oem)
        tokens = [t.strip("_.,") for t in re.split(r"[\s_]+", query.lower()) if t.strip("_.,")]
        if not tokens:
            return []
        matched: list[SimReadyAssetHit] = []

        for u in urls:
            u_lower = u.lower()
            match_count = sum(1 for t in tokens if t in u_lower)
            if match_count > 0:
                parts = u.split("/")
                folder = parts[-2] if len(parts) >= 2 else "unknown_asset"
                if oem == "ForgeCAD":
                    usd_name = f"{folder}.usda"
                else:
                    usd_name = f"sm_{folder.lower()}_01.usd"
                usd_url = u.replace("com.nvidia.simready.packaging.json", f"simready_usd/{usd_name}")
                score = match_count / float(len(tokens))

                matched.append(
                    SimReadyAssetHit(
                        id=folder,
                        name=usd_name,
                        path=u,
                        score=round(score, 4),
                        download_url=usd_url,
                        manifest_url=u,
                        dataset_id=f"{oem}/simready-assets",
                    )
                )

        matched.sort(key=lambda h: (h.score, -len(h.id)), reverse=True)
        return matched[:limit]

    def get_package_manifest(self, manifest_url: str) -> dict[str, Any]:
        """Fetch and parse a com.nvidia.simready.packaging.json manifest.

        Args:
            manifest_url: HTTPS URL to the packaging JSON.

        Returns:
            Parsed JSON dict.
        """
        req = urllib.request.Request(manifest_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read().decode())

    def download_asset(
        self,
        asset_url: str,
        asset_name: str | None = None,
        target_dir: Path | str | None = None,
        include_payloads: bool = True,
    ) -> Path:
        """Download a SimReady USD file and its referenced sublayers into the local cache.

        Args:
            asset_url: Direct resolve URL to the .usd or .usdc file.
            asset_name: Optional filename override.
            target_dir: Destination folder. Defaults to local cache dir.
            include_payloads: Whether to automatically fetch standard SimReady/ForgeCAD sublayers.

        Returns:
            Path to the downloaded USD file.
        """
        dest_dir = Path(target_dir) if target_dir else self.cache_dir
        dest_dir.mkdir(parents=True, exist_ok=True)

        if not asset_name:
            asset_name = asset_url.split("/")[-1]

        target_file = dest_dir / asset_name
        if not target_file.exists():
            self._download_url_to_file(asset_url, target_file)

        if include_payloads and "/simready_usd/" in asset_url:
            base_usd_dir = asset_url.rsplit("/", 1)[0]
            if "ForgeCAD/" in asset_url or asset_name.endswith(".usda"):
                sublayers = [
                    "forgecad/geometry.usda",
                    "forgecad/animation.usda",
                    "forgecad/physics.usda",
                    "materials/forgecad_glass.mdl",
                ]
            else:
                sublayers = [
                    "payloads/base.usda",
                    "payloads/instances.usda",
                    "payloads/instances_physx.usda",
                    "payloads/materials.usda",
                    "payloads/geometries.usd",
                    "payloads/Physics/physics.usda",
                    "payloads/PhysX/enabled.usda",
                    "payloads/PhysX/disabled.usda",
                    "payloads/MuJoCo/disabled.usda",
                    "payloads/Newton/disabled.usda",
                    "source_assets/OmniPBR.mdl",
                    "source_assets/OmniPBRBase.mdl",
                    "source_assets/OmniPBR_ClearCoat.mdl",
                ]

            # Also discover files via Hugging Face recursive tree API when available
            for tree_rel in self._discover_hf_simready_files(asset_url):
                if tree_rel not in sublayers:
                    sublayers.append(tree_rel)

            for rel_sub in sublayers:
                sub_dest = dest_dir / rel_sub
                if not sub_dest.exists():
                    sub_dest.parent.mkdir(parents=True, exist_ok=True)
                    try:
                        self._download_url_to_file(f"{base_usd_dir}/{rel_sub}", sub_dest)
                    except Exception:
                        pass

            # Parse downloaded .usda files for any additional @...@ texture/shader references
            self._download_referenced_usda_assets(dest_dir, base_usd_dir)

        return target_file

    def _discover_hf_simready_files(self, asset_url: str) -> list[str]:
        """Query Hugging Face recursive tree API for all non-thumbnail files under simready_usd/."""
        m = re.match(
            r"^https://huggingface\.co/datasets/([^/]+/[^/]+)/resolve/([^/]+)/(.+)/simready_usd/[^/]+$",
            asset_url,
        )
        if not m:
            return []
        repo, rev, folder = m.group(1), m.group(2), m.group(3)
        prefix = f"{folder}/simready_usd/"
        api_url = f"https://huggingface.co/api/datasets/{repo}/tree/{rev}/{folder}/simready_usd?recursive=true"
        req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
        discovered: list[str] = []
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
                items = json.loads(resp.read().decode())
                for item in items:
                    if item.get("type") != "file":
                        continue
                    path = item.get("path", "")
                    if not path.startswith(prefix):
                        continue
                    rel = path[len(prefix) :]
                    # Skip duplicate texture copies stored under source_assets/ when Textures/ is present
                    if rel.startswith("source_assets/") and rel.lower().endswith((".png", ".jpg", ".jpeg")):
                        continue
                    discovered.append(rel)
        except Exception:
            pass
        return discovered

    def _download_referenced_usda_assets(self, dest_dir: Path, base_usd_dir: str) -> None:
        """Scan local .usda files for @...@ asset references and fetch any missing textures or MDLs."""
        ref_pattern = re.compile(r"@([^@\n]+\.(?:png|jpg|jpeg|mdl|usd|usda|usdc))@", re.IGNORECASE)
        usda_files = list(dest_dir.rglob("*.usda"))
        for usda_file in usda_files:
            try:
                text = usda_file.read_text(encoding="utf-8", errors="ignore")
            except Exception:
                continue
            for match in ref_pattern.finditer(text):
                raw_ref = match.group(1).strip()
                if raw_ref.startswith(("http://", "https://", "omniverse://")):
                    continue
                resolved_local = (usda_file.parent / raw_ref).resolve()
                try:
                    rel_to_dest = resolved_local.relative_to(dest_dir.resolve())
                except ValueError:
                    continue
                if not resolved_local.exists():
                    resolved_local.parent.mkdir(parents=True, exist_ok=True)
                    rel_posix = rel_to_dest.as_posix()
                    try:
                        self._download_url_to_file(f"{base_usd_dir}/{rel_posix}", resolved_local)
                    except Exception:
                        pass

    @staticmethod
    def _download_url_to_file(url: str, target_file: Path) -> None:
        """Stream a URL to disk."""
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60.0) as resp, open(target_file, "wb") as f:
            chunk = resp.read(65536)
            while chunk:
                f.write(chunk)
                chunk = resp.read(65536)
