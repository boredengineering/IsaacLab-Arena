# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Cache identity without USD resolution, constructor calls or remote freshness guesses."""

import hashlib
import json
import os
import stat
from pathlib import Path


def digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def renderer_revision():
    """Fingerprint the deployed renderer implementation, not its output or timestamps."""
    root = Path(__file__).resolve().parents[3]
    paths = [
        Path(__file__).with_name(name) for name in ("snapshot_worker.py", "snapshot_service.py", "preview_options.py")
    ]
    paths += sorted((Path(__file__).resolve().parents[1] / "review_gui/simapp").glob("*.py"))
    return "arena-preview-v2-" + digest(
        [(str(path.relative_to(root)), hashlib.sha256(path.read_bytes()).hexdigest()) for path in paths]
    )


def registry_asset_revision(canonical):
    """Fail closed: the current registry exposes mutable URLs, not dependency revisions.

    AssetSpec.resolve_usd_path may instantiate/download assets, and class-level USD URLs
    do not version transitive textures, layers or robot configuration. Neither a URL,
    source-code hash nor root-USD mtime proves their freshness. A deployment may inject
    a trusted, read-only resolver of immutable full dependency-bundle revisions into
    SnapshotService; request bodies and renderer responses cannot assert this trust.
    """
    return None  # noqa: R501 -- deliberately fail closed until registry revisions exist.


class LocalAssetRevisions:
    """Fingerprint explicitly trusted, complete local dependency bundles.

    Supply this callable as SnapshotService(asset_revision=...) from server composition,
    never from a request or an unverified worker manifest. Each registry name must map
    to its complete dependency closure: USD layers, textures, robot/config sources and
    any constructor-dependent resources. Omitted names, URLs and symlinks fail closed.
    This does not discover USD dependencies or assert completeness on the caller's behalf.
    """

    def __init__(self, bundles):
        self.bundles = {name: tuple(Path(path) for path in paths) for name, paths in bundles.items()}

    def __call__(self, canonical):
        names = {
            asset["registry_name"]
            for asset in [canonical["embodiment"], canonical["background"], *canonical.get("objects", [])]
        }
        paths = set()
        for name in names:
            bundle = self.bundles.get(name)
            if not bundle:
                return None
            paths.update(bundle)
        if len(paths) > 256:
            return None
        fingerprints = []
        total = 0
        try:
            for path in sorted(paths):
                if not path.is_absolute() or path.resolve() != path:
                    return None
                fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(fd, "rb") as stream:
                    before = os.fstat(stream.fileno())
                    total += before.st_size
                    if not stat.S_ISREG(before.st_mode) or total > 128 * 1024 * 1024:
                        return None
                    content = stream.read(128 * 1024 * 1024 + 1)
                    after = os.fstat(stream.fileno())
                    if (before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
                        after.st_size,
                        after.st_mtime_ns,
                        after.st_ctime_ns,
                    ) or len(content) != before.st_size:
                        return None
                    fingerprints.append((str(path), hashlib.sha256(content).hexdigest()))
        except OSError:
            return None
        return digest([sorted(names), fingerprints])
