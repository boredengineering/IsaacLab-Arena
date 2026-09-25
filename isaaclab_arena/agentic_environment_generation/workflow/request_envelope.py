# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Frozen request assumptions and explicit conservative, conditional price derivations.

Neither a registered bound nor a synthetic pricing fixture verifies provider rates
or grants execution. Byte ceilings alone are not token estimates or billing.
"""

import base64
import binascii
import json
import math
import struct
from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Annotated, Literal

from pydantic import Field, model_validator

from .accounting import _usd_units, checked_workflow_accounting
from .contracts import Count, FrozenModel, Identifier, Text

PositiveBound = Annotated[int, Field(strict=True, gt=0, le=1_000_000_000)]
BoundsVersion = Annotated[int, Field(strict=True, ge=1, le=1)]


class RequestLimits(FrozenModel):
    """Public envelope fields; literal model, endpoint and accounting come from the profile."""

    version: BoundsVersion
    max_text_bytes: PositiveBound
    max_schema_bytes: PositiveBound
    max_request_bytes: PositiveBound
    output_parameter: Literal["max_tokens", "max_completion_tokens"]
    max_output_tokens: PositiveBound
    image_formats: tuple[Literal["png"], ...]
    max_images: Count
    max_image_bytes: PositiveBound
    max_image_width: PositiveBound
    max_image_height: PositiveBound
    image_detail: Literal["auto", "low", "high"]
    permitted_fields: tuple[str, ...]
    route_policy: Literal["direct-chat-completions-v1"]


class PricingBasis(FrozenModel):
    """Explicit universal upper-bound assumptions; v1 installed evidence is synthetic only.

    The input multiplier must cover all non-image billable input, including
    message overhead and schema. The additional per-image tokens cover the worst
    admitted dimensions/detail. Output includes default reasoning. Full price is
    charged even for failed or uncertain sends, without cache or retry discounts.
    """

    version: BoundsVersion
    revision: Identifier
    kind: Literal["synthetic_fixture"]
    source: Text
    provider: Literal["openai"]
    input_tokens_per_request_byte: PositiveBound
    image_tokens_per_image: Count
    input_usd_per_million_tokens: str
    output_usd_per_million_tokens: str
    per_request_usd: str
    assumptions: Annotated[tuple[Text, ...], Field(min_length=1, max_length=16)]

    @model_validator(mode="after")
    def prices(self):
        for price in (self.input_usd_per_million_tokens, self.output_usd_per_million_tokens, self.per_request_usd):
            _usd_units(price)
        return self


class RequestBounds(FrozenModel):
    """Versioned profile binding of an executable envelope and reviewable price basis."""

    version: Annotated[int, Field(strict=True, ge=1, le=2)]
    envelope: RequestLimits
    pricing: PricingBasis | None

    @model_validator(mode="after")
    def explicit_accounting_policy(self):
        if (self.version == 2) != (self.pricing is None):
            raise ValueError("V2 records actual usage/unknown cost; V1 requires bounded pricing")
        return self

    def accounting(self, *, model, endpoint):
        """Derive the universal per-send ceiling with exact integer nano-USD rounding."""
        limits, price = self.envelope, self.pricing
        if self.version == 2:
            return checked_workflow_accounting(
                dict(version=2, attested=False, model=model, endpoint=endpoint, max_tokens=None, max_cost_usd=None)
            )
        if limits.max_images and price.image_tokens_per_image == 0:
            raise ValueError("Explicit worst-case image token allowance required")
        inputs = (
            limits.max_request_bytes * price.input_tokens_per_request_byte
            + limits.max_images * price.image_tokens_per_image
        )
        # Round each positive fractional nano-USD upwards, never down to free.
        units = _usd_units(price.per_request_usd)
        units += (inputs * _usd_units(price.input_usd_per_million_tokens) + 999999) // 1000000
        units += (limits.max_output_tokens * _usd_units(price.output_usd_per_million_tokens) + 999999) // 1000000
        whole, fraction = divmod(units, 10**9)
        return checked_workflow_accounting(
            dict(
                version=1,
                attested=True,
                model=model,
                endpoint=endpoint,
                max_tokens=inputs + limits.max_output_tokens,
                max_cost_usd=f"{whole}.{fraction:09d}",
            )
        )

    def bind(self, *, model, endpoint, accounting, inference_policy):
        """Reject mismatched settings before returning the existing final-request guard."""
        expected = self.accounting(model=model, endpoint=endpoint)
        observed = checked_workflow_accounting(accounting, model=model, endpoint=endpoint)
        if (
            any(expected[k] != observed[k] for k in expected if k != "max_cost_usd")
            or (self.version == 1 and _usd_units(expected["max_cost_usd"]) != _usd_units(observed["max_cost_usd"]))
            or type(inference_policy) is not dict
            or inference_policy.get("provider") != (self.pricing.provider if self.pricing else "openai")
            or inference_policy.get("model") != model
            or inference_policy.get("endpoint", "").rstrip("/") != endpoint.rstrip("/")
            or inference_policy.get("request_policy", {}).get("token_limit_parameter") != self.envelope.output_parameter
        ):
            raise ValueError("Request/pricing binding mismatch")
        return RequestEnvelope(
            **self.envelope.model_dump(mode="json"), model=model, endpoint=endpoint, accounting=observed
        )


def _json_copy(value):
    """Detach a plain JSON tree; never invoke caller-supplied serializer methods."""
    if type(value) is dict and all(type(k) is str for k in value):
        return {k: _json_copy(v) for k, v in value.items()}
    if type(value) is list:
        return [_json_copy(v) for v in value]
    if value is None or type(value) in (str, bool, int):
        return value
    if type(value) is float and math.isfinite(value):
        return value
    raise ValueError("request envelope requires plain finite JSON")


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("request envelope duplicate JSON key")
        result[key] = value
    return result


@dataclass(frozen=True)
class RequestEnvelope:
    """Freeze request assumptions, not prices or authority, separately from run budgets.

    V1 admits direct official OpenAI chat completions only; gateways, routing,
    tools, audio, streaming, multiple completions and optional reasoning/service
    parameters are unsupported. Default reasoning must be covered by the trusted
    total attestation; max_completion_tokens includes the output/reasoning cap.
    Provider rates, default semantics and failed-call charges remain unverified.

    Text is aggregate UTF-8 message text (including catalogues/prior/feedback).
    Schema is the complete response_format reserialized as ASCII JSON with
    default separators; it is a conservative semantic bound, not a raw fragment
    measurement. Whole-request size is actual JSON bytes plus method, absolute
    URL, raw header names/values and five delimiter bytes plus four per header.
    It excludes TLS/HTTP framing and is not a memory or provider-token bound.

    Images are inline noninterlaced 8-bit PNG with IHDR/IDAT/IEND only, checked
    CRCs and dimensions; compressed pixels are not decoded. No animation,
    metadata chunks, external URLs or other formats are admitted. Bytes are
    per image; count aggregates all messages. Omitted detail means auto and is
    admitted only by an explicit auto contract, whose worst case is attested.
    """

    version: int
    model: str
    endpoint: str
    accounting: Mapping
    max_text_bytes: int
    max_schema_bytes: int
    max_request_bytes: int
    output_parameter: str
    max_output_tokens: int
    image_formats: tuple[str, ...]
    max_images: int
    max_image_bytes: int
    max_image_width: int
    max_image_height: int
    image_detail: str
    permitted_fields: tuple[str, ...]
    route_policy: str

    def __post_init__(self):
        limits = (
            self.max_text_bytes,
            self.max_schema_bytes,
            self.max_request_bytes,
            self.max_output_tokens,
            self.max_image_bytes,
            self.max_image_width,
            self.max_image_height,
        )
        if (
            type(self.version) is not int
            or self.version != 1
            or any(type(v) is not int or v <= 0 for v in limits)
            or type(self.max_images) is not int
            or self.max_images < 0
            or self.output_parameter not in ("max_tokens", "max_completion_tokens")
            or self.route_policy != "direct-chat-completions-v1"
            or self.endpoint not in ("https://api.openai.com/v1", "https://api.openai.com/v1/")
            or self.image_detail not in ("auto", "low", "high")
            or type(self.image_formats) not in (list, tuple)
            or any(type(v) is not str or v != "png" for v in self.image_formats)
            or len(self.image_formats) > 1
            or type(self.permitted_fields) not in (list, tuple)
            or any(type(v) is not str for v in self.permitted_fields)
        ):
            raise ValueError("unsupported request envelope contract")
        permitted = set(self.permitted_fields)
        if (
            len(permitted) != len(self.permitted_fields)
            or not {"model", "messages", self.output_parameter} <= permitted
            or not permitted
            <= {
                "model",
                "messages",
                self.output_parameter,
                "temperature",
                "store",
                "response_format",
            }
        ):
            raise ValueError("unsupported request envelope fields")
        accounting = checked_workflow_accounting(self.accounting, model=self.model, endpoint=self.endpoint)
        if accounting["version"] == 1 and self.max_output_tokens > accounting["max_tokens"]:
            raise ValueError("request envelope output exceeds attested total")
        object.__setattr__(self, "accounting", MappingProxyType(accounting))
        object.__setattr__(self, "image_formats", tuple(self.image_formats))
        object.__setattr__(self, "permitted_fields", tuple(self.permitted_fields))

    def check_binding(self, *, model, endpoint, accounting):
        """Require literal endpoint/model and the complete original accounting identity."""
        if self.model != model or self.endpoint != endpoint or dict(self.accounting) != accounting:
            raise ValueError("request envelope binding mismatch")

    def check_request(self, request):
        """Bound actual serialized JSON body bytes, not a reconstructed token estimate."""
        raw = request.content
        if len(raw) > self.max_request_bytes:
            raise ValueError("request envelope serialized body limit")
        body = _json_copy(json.loads(raw, object_pairs_hook=_unique_object))
        self.check_body(body)

    def copy_arguments(self, args, kwargs):
        """Reject SDK escape hatches even when their values would serialize away."""
        if args or not set(kwargs) <= set(self.permitted_fields):
            raise ValueError("request envelope unsupported SDK arguments")
        return _json_copy(kwargs)

    def check_body(self, body):
        """Admit only single nonstreaming text/schema chat completions."""
        if (
            type(body) is not dict
            or not set(body) <= set(self.permitted_fields)
            or not {"model", "messages", self.output_parameter} <= set(body)
            or body["model"] != self.model
            or type(body[self.output_parameter]) is not int
            or not 0 < body[self.output_parameter] <= self.max_output_tokens
            or ("store" in body and body["store"] is not False)
            or (
                "temperature" in body
                and (type(body["temperature"]) not in (int, float) or not 0 <= body["temperature"] <= 2)
            )
        ):
            raise ValueError("request envelope body policy")
        messages = body["messages"]
        if type(messages) is not list or not messages:
            raise ValueError("request envelope messages policy")
        text_bytes = images = 0
        for message in messages:
            if (
                type(message) is not dict
                or set(message) != {"role", "content"}
                or message["role"] not in ("system", "user", "assistant")
            ):
                raise ValueError("request envelope message policy")
            content = message["content"]
            if type(content) is str:
                text_bytes += len(content.encode("utf-8"))
            else:
                if type(content) is not list or not content:
                    raise ValueError("request envelope content policy")
                for part in content:
                    if type(part) is dict and set(part) == {"type", "image_url"} and part["type"] == "image_url":
                        images += 1
                        if images > self.max_images:
                            raise ValueError("request envelope aggregate image count")
                        self.check_image(part["image_url"])
                        continue
                    if type(part) is not dict or set(part) != {"type", "text"} or part["type"] != "text":
                        raise ValueError("request envelope content part policy")
                    if type(part["text"]) is not str:
                        raise ValueError("request envelope text policy")
                    text_bytes += len(part["text"].encode("utf-8"))
        if text_bytes > self.max_text_bytes:
            raise ValueError("request envelope aggregate text limit")
        schema = body.get("response_format")
        if "response_format" in body:
            if schema != {"type": "json_object"}:
                if (
                    type(schema) is not dict
                    or set(schema) != {"type", "json_schema"}
                    or schema["type"] != "json_schema"
                    or type(schema["json_schema"]) is not dict
                    or set(schema["json_schema"]) != {"name", "strict", "schema"}
                    or type(schema["json_schema"]["name"]) is not str
                    or schema["json_schema"]["strict"] is not True
                    or type(schema["json_schema"]["schema"]) is not dict
                ):
                    raise ValueError("request envelope response schema policy")
            if len(json.dumps(schema, ensure_ascii=True).encode("utf-8")) > self.max_schema_bytes:
                raise ValueError("request envelope schema limit")

    def check_image(self, image):
        """Admit bounded inline single-frame PNG chunks; this is not a pixel decoder."""
        if (
            type(image) is not dict
            or not {"url"} <= set(image) <= {"url", "detail"}
            or image.get("detail", "auto") != self.image_detail
            or type(image["url"]) is not str
            or "png" not in self.image_formats
            or not image["url"].startswith("data:image/png;base64,")
        ):
            raise ValueError("request envelope inline image policy")
        encoded = image["url"][len("data:image/png;base64,") :]
        if len(encoded) > 4 * ((self.max_image_bytes + 2) // 3):
            raise ValueError("request envelope image bytes")
        try:
            raw = base64.b64decode(encoded, validate=True)
        except (ValueError, binascii.Error):
            raise ValueError("request envelope image encoding") from None
        if len(raw) > self.max_image_bytes or not raw.startswith(b"\x89PNG\r\n\x1a\n"):
            raise ValueError("request envelope image bytes/signature")
        offset, seen_data = 8, False
        while offset + 12 <= len(raw):
            size = int.from_bytes(raw[offset : offset + 4], "big")
            kind = raw[offset + 4 : offset + 8]
            end = offset + 12 + size
            if end > len(raw) or kind not in (b"IHDR", b"IDAT", b"IEND"):
                raise ValueError("request envelope PNG chunks")
            data = raw[offset + 8 : end - 4]
            if binascii.crc32(kind + data) != int.from_bytes(raw[end - 4 : end], "big"):
                raise ValueError("request envelope PNG checksum")
            if kind == b"IHDR" and offset != 8:
                raise ValueError("request envelope duplicate PNG header")
            if offset == 8:
                if kind != b"IHDR" or size != 13:
                    raise ValueError("request envelope PNG header")
                width, height, depth, color, compression, filtering, interlace = struct.unpack(">IIBBBBB", data)
                if (
                    not 0 < width <= self.max_image_width
                    or not 0 < height <= self.max_image_height
                    or depth != 8
                    or color not in (0, 2, 4, 6)
                    or (compression, filtering, interlace) != (0, 0, 0)
                ):
                    raise ValueError("request envelope PNG dimensions/format")
            elif kind == b"IDAT":
                seen_data = True
            elif kind == b"IEND":
                if size != 0 or end != len(raw) or not seen_data:
                    raise ValueError("request envelope PNG end")
                return
            offset = end
        raise ValueError("request envelope incomplete PNG")

    def check_http(self, request, *, api_key):
        """Check the exact route and closed HTTP header surface without logging secrets."""
        allowed = {
            "host",
            "accept-encoding",
            "connection",
            "authorization",
            "accept",
            "content-type",
            "user-agent",
            "x-stainless-lang",
            "x-stainless-package-version",
            "x-stainless-os",
            "x-stainless-arch",
            "x-stainless-runtime",
            "x-stainless-runtime-version",
            "x-stainless-async",
            "x-stainless-retry-count",
            "x-stainless-read-timeout",
            "content-length",
        }
        headers = request.headers
        # Conservative explicit serialization measure, not TLS/HTTP2 framing or RSS.
        size = len(request.content) + len(request.method.encode()) + len(str(request.url).encode()) + 5
        size += sum(len(k) + len(v) + 4 for k, v in headers.raw)
        if size > self.max_request_bytes:
            raise ValueError("request envelope whole serialized request limit")
        if (
            request.method != "POST"
            or str(request.url) != self.endpoint.rstrip("/") + "/chat/completions"
            or not set(headers) <= allowed
            or len(headers.multi_items()) != len(headers)
            or headers.get("content-type") != "application/json"
            or headers.get("authorization") != "Bearer " + api_key
            or headers.get("host") != request.url.netloc.decode("ascii")
            or headers.get("content-length") != str(len(request.content))
        ):
            raise ValueError("request envelope HTTP route/header policy")
        self.check_request(request)
