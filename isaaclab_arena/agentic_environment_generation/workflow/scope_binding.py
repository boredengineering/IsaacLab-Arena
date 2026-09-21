# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Explicit public operational identity, independent of artifact location/identity."""

import hashlib
from typing import Annotated

from pydantic import Field

from .contracts import Identifier
from .profiles import ProfileScope, profile_json

MAX_BINDING_BYTES = 4096
BindingVersion = Annotated[int, Field(strict=True, ge=1, le=1)]
ArtifactIdentity = Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")]


class ScopeBinding(ProfileScope):
    """Codec 1 pins explicit authority and existing marker IDs, never registry contents.

    Paths are trusted configuration, not identity. Artifact store_id is NOT the
    operational authority. This record is not execution permission or readiness.
    """

    schema_version: BindingVersion
    authority_id: Identifier
    operational_schema_version: BindingVersion
    artifact_marker_schema: BindingVersion
    store_id: ArtifactIdentity
    registry_id: ArtifactIdentity

    @property
    def body_json(self):
        return profile_json(self.model_dump(mode="json"))

    @property
    def body_sha256(self):
        return hashlib.sha256(self.body_json.encode("utf-8")).hexdigest()


class CorruptScopeBinding(ValueError):
    """Invalid retained binding; messages never include retained inputs."""


class ScopeMigrationRequired(ValueError):
    """An existing legacy control cannot be implicitly stamped or adopted."""


def decode_scope_binding(body, digest):
    """Decode only retained local bytes; callers keep IO outside this boundary."""
    try:
        if type(body) is not str or len(body.encode("utf-8")) > MAX_BINDING_BYTES:
            raise ValueError("Invalid binding body")
        value = ScopeBinding.model_validate_json(body)
        if body != value.body_json or type(digest) is not str or digest != value.body_sha256:
            raise ValueError("Invalid binding digest or canonical bytes")
        return value
    except (ValueError, TypeError, RecursionError):
        raise CorruptScopeBinding("Invalid retained scope binding") from None
