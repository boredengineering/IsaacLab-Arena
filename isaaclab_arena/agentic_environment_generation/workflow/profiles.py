# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Immutable public model catalogue codec and byte-compatible legacy settings hash.

Structural validity is not current-catalogue admission, configured credentials,
role compatibility, readiness or execution permission. New registrations need
separate current-catalogue checking after exact durable replay lookup.
"""

import hashlib
import json
from typing import Annotated, Literal

from pydantic import Field, model_serializer, model_validator

from ..inference_profiles import checked_request_policy
from .contracts import FrozenModel, Hash, Identifier
from .request_envelope import RequestBounds

MAX_PROFILE_BYTES = 16 * 1024
MAX_PROFILE_REVISIONS = 64
CatalogueRevision = Annotated[int, Field(strict=True, gt=0, le=2**63 - 1)]
ModelName = Annotated[str, Field(strict=True, pattern=r"^[!-~]{1,256}$")]


def profile_json(value):
    """Encode public catalogue v1 bytes without changing literal settings."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


class CorruptProfileRecord(ValueError):
    """Retained profile bytes are invalid; never expose their validation inputs."""


class PublicRequestPolicy(FrozenModel):
    """Frozen fields of the existing checked request-policy codec."""

    api: Literal["chat_completions"]
    temperature_mode: Literal["configured", "omitted"]
    token_limit_parameter: Literal["max_tokens", "max_completion_tokens"]
    structured_output: Literal["json_schema", "json_object", "omitted"]
    multimodal_output: Literal["json_object", "omitted"]
    store: Literal[False] | None

    @model_validator(mode="before")
    @classmethod
    def checked(cls, value):
        return checked_request_policy(value)


class PublicInferencePolicy(FrozenModel):
    id: Annotated[str, Field(strict=True, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")]
    revision: Annotated[int, Field(strict=True, ge=1, le=1)]
    provider: Literal["openai", "gemini", "openrouter", "nvidia"]
    model: ModelName
    endpoint: str
    origin: Literal["builtin", "user_defined"]
    support: Literal["documented", "unverified"]
    verification: Literal["not_checked"]
    documentation_urls: tuple[str, ...]
    request_policy: PublicRequestPolicy

    @model_validator(mode="after")
    def stable_structure(self):
        # Catalogue codec v1 literals are immutable history, NOT current endpoint
        # permission. New registration separately checks checked_inference_profile.
        codec_bindings = (
            ("openai", "https://api.openai.com/v1"),
            ("gemini", "https://generativelanguage.googleapis.com/v1beta/openai/"),
            ("openrouter", "https://openrouter.ai/api/v1"),
            ("nvidia", "https://integrate.api.nvidia.com/v1"),
        )
        if self.id == "custom" or (self.provider, self.endpoint) not in codec_bindings:
            raise ValueError("Invalid inference policy binding")
        if self.origin == "user_defined" and (self.support != "unverified" or self.documentation_urls):
            raise ValueError("User-defined inference policies are unverified")
        return self


class PublicWorkflowAccounting(FrozenModel):
    version: Annotated[int, Field(strict=True, ge=1, le=2)]
    attested: Literal[True, False]
    model: str
    endpoint: str
    max_tokens: Annotated[int, Field(strict=True, gt=0)] | None
    max_cost_usd: str | None

    @model_validator(mode="before")
    @classmethod
    def checked(cls, value):
        from .accounting import checked_workflow_accounting

        return checked_workflow_accounting(value)


class PublicModelSettings(FrozenModel):
    model: ModelName
    endpoint: str
    billing: Literal["free", "paid"]
    inference_policy: PublicInferencePolicy | None
    workflow_accounting: PublicWorkflowAccounting | None = None
    request_bounds: RequestBounds | None = None

    @model_serializer(mode="wrap")
    def compatible_bytes(self, handler):
        value = handler(self)
        if self.request_bounds is None:
            value.pop("request_bounds", None)
        return value

    @model_validator(mode="after")
    def bindings(self):
        policy = self.inference_policy
        if policy is not None and (
            self.model != policy.model or self.endpoint not in (policy.endpoint, policy.endpoint.rstrip("/") + "/")
        ):
            raise ValueError("Public settings do not match inference policy")
        if self.workflow_accounting is not None and (
            self.model != self.workflow_accounting.model or self.endpoint != self.workflow_accounting.endpoint
        ):
            raise ValueError("Public accounting does not match literal settings")
        if self.request_bounds is not None:
            if self.workflow_accounting is None or self.inference_policy is None:
                raise ValueError("Complete request/pricing settings required")
            self.request_bounds.bind(
                model=self.model,
                endpoint=self.endpoint,
                accounting=self.workflow_accounting.model_dump(mode="json"),
                inference_policy=self.inference_policy.model_dump(mode="json"),
            )
        return self


def public_model_settings_sha256(settings: PublicModelSettings) -> str:
    """Hash legacy v1 public bytes; absent accounting is omitted, null policy retained."""
    value = settings.model_dump(mode="json")
    if settings.workflow_accounting is None:
        value.pop("workflow_accounting")
    return hashlib.sha256(profile_json({"version": 1, **value}).encode("utf-8")).hexdigest()


class ProfileRegistration(FrozenModel):
    profile_id: Identifier
    revision: CatalogueRevision
    kind: Literal["model"]
    roles: tuple[Literal["generation_model", "assessment_model"], ...]
    settings: PublicModelSettings

    @model_validator(mode="after")
    def canonical_roles(self):
        if self.settings.inference_policy is None:
            raise ValueError("Explicit inference policy required for registration")
        if not self.roles or len(self.roles) != len(set(self.roles)):
            raise ValueError("Nonempty duplicate-free model roles required")
        object.__setattr__(self, "roles", tuple(sorted(self.roles)))
        if len(profile_json(self.model_dump(mode="json")).encode("utf-8")) > MAX_PROFILE_BYTES:
            raise ValueError("Public profile body exceeds byte bound")
        return self


class ProfileScope(FrozenModel):
    database: Identifier
    deployment_id: Identifier
    workspace_id: Identifier


class ProfileIdentity(FrozenModel):
    profile_id: Identifier
    revision: CatalogueRevision


class ProfileRevision(FrozenModel):
    """Retained catalogue codec v1; revisions do not imply readiness or permission.

    The explicit outer codec version is separate from catalogue and policy
    revisions. Its canonical envelope is included in the body digest, never the
    legacy settings hash. No default revision is added to workflow references.
    """

    schema_version: Annotated[int, Field(strict=True, ge=1, le=1)]
    registration: ProfileRegistration
    body_sha256: Hash
    settings_sha256: Hash

    @model_validator(mode="after")
    def digests(self):
        if self.body_sha256 != hashlib.sha256(
            profile_body(self.registration).encode("utf-8")
        ).hexdigest() or self.settings_sha256 != public_model_settings_sha256(self.registration.settings):
            raise ValueError("Profile digest binding differs")
        return self

    @property
    def profile_id(self):
        return self.registration.profile_id

    @property
    def revision(self):
        return self.registration.revision


def profile_body(registration: ProfileRegistration) -> str:
    """Encode the supported explicit catalogue envelope, bounded including version."""
    body = profile_json({"schema_version": 1, "registration": registration.model_dump(mode="json")})
    if len(body.encode("utf-8")) > MAX_PROFILE_BYTES:
        raise ValueError("Public profile body exceeds byte bound")
    return body


def profile_revision(registration: ProfileRegistration) -> ProfileRevision:
    return ProfileRevision(
        schema_version=1,
        registration=registration,
        body_sha256=hashlib.sha256(profile_body(registration).encode("utf-8")).hexdigest(),
        settings_sha256=public_model_settings_sha256(registration.settings),
    )
