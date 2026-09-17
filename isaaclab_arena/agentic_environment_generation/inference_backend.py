# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible structured-output inference backend for agent inference steps."""

from __future__ import annotations

import base64
import contextlib
import copy
import json
import os
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from openai import APIStatusError, OpenAI
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel

from isaaclab_arena.agentic_environment_generation import inference_profiles


def _load_dotenv_if_present() -> None:
    """Load environment variables from local untracked .env files if present."""
    search_paths = [
        Path(".env"),
        Path("/workspaces/isaaclab_arena/.env"),
        Path("/workspaces/IsaacLab-Arena/.env"),
        Path.home() / ".env",
    ]
    for p in search_paths:
        if p.exists():
            with contextlib.suppress(Exception):
                with open(p, encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("\"'")
                            if key not in os.environ:
                                os.environ[key] = val


MAX_RETRIES_LIMIT = 10

# TODO(qianl): This is currently Nvidia internal. Switch to public endpoint.
DEFAULT_BASE_URL = "https://inference-api.nvidia.com"
DEFAULT_MODEL = "azure/anthropic/claude-opus-4-8"

DEFAULT_OPENROUTER_MODEL = "anthropic/claude-sonnet-4.5"

# Complete Anthropic models catalog supported via OpenRouter
ANTHROPIC_MODELS: dict[str, str] = {
    # Flagship Sonnet Models (1M Context)
    "claude-sonnet-4.5": "anthropic/claude-sonnet-4.5",
    "claude-sonnet-4.6": "anthropic/claude-sonnet-4.6",
    "claude-sonnet-5": "anthropic/claude-sonnet-5",
    "claude-sonnet-4": "anthropic/claude-sonnet-4",
    # Flagship Opus Reasoning Models (1M Context)
    "claude-opus-4.5": "anthropic/claude-opus-4.5",
    "claude-opus-4.6": "anthropic/claude-opus-4.6",
    "claude-opus-4.7": "anthropic/claude-opus-4.7",
    "claude-opus-4.8": "anthropic/claude-opus-4.8",
    "claude-opus-5": "anthropic/claude-opus-5",
    "claude-opus-4": "anthropic/claude-opus-4",
    "claude-opus-4.1": "anthropic/claude-opus-4.1",
    # High-Efficiency Haiku Models (200k Context)
    "claude-haiku-4.5": "anthropic/claude-haiku-4.5",
    "claude-3-haiku": "anthropic/claude-3-haiku",
    # Research / Fable Architectures
    "claude-fable-5": "anthropic/claude-fable-5",
    "claude-fable-5.1": "anthropic/claude-fable-5.1",
    # Floating Latest Pointer Aliases
    "claude-sonnet-latest": "~anthropic/claude-sonnet-latest",
    "claude-opus-latest": "~anthropic/claude-opus-latest",
    "claude-haiku-latest": "~anthropic/claude-haiku-latest",
    "claude-fable-latest": "~anthropic/claude-fable-latest",
}


@dataclass
class InferenceCallMetrics:
    """Telemetry recorded for a single LLM API completion call."""

    stage: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    duration_s: float = 0.0
    model: str = ""
    success: bool = True


@dataclass
class InferenceTelemetryTracker:
    """Thread-safe accumulator for inference metrics across multiple agent stages."""

    calls: list[InferenceCallMetrics] = field(default_factory=list)

    @property
    def total_calls(self) -> int:
        """Total number of inference calls executed."""
        return len(self.calls)

    @property
    def total_prompt_tokens(self) -> int:
        """Total prompt tokens ingested across all calls."""
        return sum(c.prompt_tokens for c in self.calls)

    @property
    def total_completion_tokens(self) -> int:
        """Total completion tokens generated across all calls."""
        return sum(c.completion_tokens for c in self.calls)

    @property
    def total_tokens(self) -> int:
        """Total tokens (prompt + completion) consumed."""
        return sum(c.total_tokens for c in self.calls)

    @property
    def total_duration_s(self) -> float:
        """Total inference API wall-clock duration in seconds."""
        return sum(c.duration_s for c in self.calls)

    def calls_by_stage(self, stage: str) -> list[InferenceCallMetrics]:
        """Filter call metrics for a specific pipeline stage."""
        return [c for c in self.calls if c.stage == stage]


@dataclass(frozen=True)
class StructuredOutputRequest:
    """One JSON-schema structured-output chat completion."""

    schema_name: str
    schema: dict[str, Any]
    system: str
    user: str
    retry_label: str
    parse_json: Callable[[str], dict[str, Any]] | None = None
    """Optional raw-content parser; None preserves legacy tolerant parsing."""


def completion_request_parameters(
    *,
    model: str,
    base_url: str,
    temperature: float,
    max_tokens: int,
    ping: bool = False,
    configured_base_url: str | None = None,
    inference_profile: dict | None = None,
) -> dict[str, Any]:
    """Select chat parameters for an exact model and actual client endpoint.

    Only ``gpt-6-astra`` on the official OpenAI v1 endpoint uses the Astra
    profile: no sampling temperature, explicit ``store=False``, and the same
    token ceiling expressed as ``max_completion_tokens`` (including reasoning).
    The initializer uses at most eight tokens, never more than that ceiling.
    Every other pair retains the legacy temperature/max_tokens profile, including
    its eight-token ping. This pure helper is also the source for future profile
    reporting; it does not infer model families or provider identity from substrings.
    ``store=False`` opts out of completion storage, not provider abuse-log retention.
    """
    profile = (inference_profiles.checked_inference_profile(inference_profile, model=model, base_url=base_url)
               if inference_profile is not None else inference_profiles.resolve_inference_profile(
                   model, base_url if configured_base_url is None else configured_base_url, actual_base_url=base_url))
    if profile is not None:
        policy = profile["request_policy"]
        omitted = policy["temperature_mode"] == "omitted"
        ceiling = (min(8, max_tokens) if omitted or inference_profile is not None else 8) if ping else max_tokens
        parameters: dict[str, Any] = {policy["token_limit_parameter"]: ceiling}
        if not omitted:
            parameters["temperature"] = temperature
        if policy["store"] is not None:
            parameters["store"] = policy["store"]
        return parameters
    return {"temperature": temperature, "max_tokens": 8 if ping else max_tokens}


class InferenceBackend:
    """Shared LLM JSON-schema runner with retry and tolerant JSON parsing."""

    _explicit_profile = None

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
        load_dotenv: bool = True,
        inference_profile: dict | None = None,
    ):
        """Configure an OpenAI-compatible structured-output client.

        Args:
            api_key: API token for the inference endpoint. Falls back to the
                ``NV_API_KEY`` environment variable.
            model: Model identifier passed to the chat completion API.
            base_url: OpenAI-compatible inference endpoint.
            temperature: Sampling temperature for completion requests.
            max_tokens: Maximum tokens in each completion response.
            max_retries: Additional attempts after a recoverable failure; must be in
                ``[0, MAX_RETRIES_LIMIT)``.
            load_dotenv: Load local credential files for legacy CLI callers; disable in servers.
        """
        assert (
            0 <= max_retries < MAX_RETRIES_LIMIT
        ), f"max_retries must be in [0, {MAX_RETRIES_LIMIT}), got {max_retries}"
        self._explicit_profile = (inference_profiles.checked_inference_profile(
            inference_profile, model=model, base_url=base_url) if inference_profile is not None else None)
        if self._explicit_profile is not None and (model is None or base_url is None):
            raise ValueError("Explicit inference profiles require literal model and endpoint")
        if load_dotenv:
            _load_dotenv_if_present()
        candidate_model = (
            model or os.getenv("OPENAI_MODEL") or os.getenv("GEMINI_MODEL") or os.getenv("OPENROUTER_MODEL") or ""
        )

        if api_key:
            resolved_api_key = api_key
        elif ("gpt" in candidate_model or "astra" in candidate_model) and os.getenv("OPENAI_API_KEY"):
            resolved_api_key = os.getenv("OPENAI_API_KEY")
        elif "gemini" in candidate_model and os.getenv("GEMINI_API_KEY"):
            resolved_api_key = os.getenv("GEMINI_API_KEY")
        elif ("claude" in candidate_model or "anthropic" in candidate_model) and os.getenv("OPENROUTER_API_KEY"):
            resolved_api_key = os.getenv("OPENROUTER_API_KEY")
        else:
            resolved_api_key = (
                os.getenv("OPENAI_API_KEY")
                or os.getenv("GEMINI_API_KEY")
                or os.getenv("OPENROUTER_API_KEY")
                or os.getenv("NV_API_KEY")
            )
        assert (
            resolved_api_key
        ), "API key required: set OPENAI_API_KEY, GEMINI_API_KEY, OPENROUTER_API_KEY, NV_API_KEY, or pass api_key."

        if base_url is not None:
            is_openrouter = "openrouter.ai" in base_url
            is_gemini = "generativelanguage.googleapis.com" in base_url
            is_openai = "api.openai.com" in base_url
        elif resolved_api_key.startswith("sk-or-") or (
            os.getenv("OPENROUTER_API_KEY") and resolved_api_key == os.getenv("OPENROUTER_API_KEY")
        ):
            is_openrouter, is_gemini, is_openai = True, False, False
        elif resolved_api_key.startswith("AIza") or (
            os.getenv("GEMINI_API_KEY") and resolved_api_key == os.getenv("GEMINI_API_KEY")
        ):
            is_openrouter, is_gemini, is_openai = False, True, False
        elif resolved_api_key.startswith("sk-") or (
            os.getenv("OPENAI_API_KEY") and resolved_api_key == os.getenv("OPENAI_API_KEY")
        ):
            is_openrouter, is_gemini, is_openai = False, False, True
        else:
            is_openrouter = bool(os.getenv("OPENROUTER_BASE_URL"))
            is_gemini = bool(os.getenv("GEMINI_BASE_URL"))
            is_openai = bool(os.getenv("OPENAI_BASE_URL"))

        if is_openrouter:
            resolved_base_url = (
                base_url or os.getenv("OPENROUTER_BASE_URL") or os.getenv("BASE_URL") or "https://openrouter.ai/api/v1"
            )
            default_model_id = os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL
        elif is_gemini:
            resolved_base_url = (
                base_url
                or os.getenv("GEMINI_BASE_URL")
                or os.getenv("BASE_URL")
                or "https://generativelanguage.googleapis.com/v1beta/openai/"
            )
            default_model_id = os.getenv("GEMINI_MODEL") or "gemini-2.5-flash"
        elif is_openai:
            resolved_base_url = (
                base_url or os.getenv("OPENAI_BASE_URL") or os.getenv("BASE_URL") or "https://api.openai.com/v1"
            )
            default_model_id = os.getenv("OPENAI_MODEL") or "gpt-6-astra"
        else:
            resolved_base_url = base_url or os.getenv("NV_BASE_URL") or os.getenv("BASE_URL") or DEFAULT_BASE_URL
            default_model_id = DEFAULT_MODEL

        raw_model = (
            model
            or (os.getenv("OPENROUTER_MODEL") if is_openrouter else None)
            or (os.getenv("GEMINI_MODEL") if is_gemini else None)
            or os.getenv("OPENAI_MODEL")
            or os.getenv("NV_MODEL")
            or default_model_id
        )
        if self._explicit_profile is not None:
            resolved_model = raw_model
        elif is_openrouter and raw_model in ANTHROPIC_MODELS:
            resolved_model = ANTHROPIC_MODELS[raw_model]
        elif is_openrouter and raw_model.startswith("claude-") and not raw_model.startswith("anthropic/"):
            resolved_model = f"anthropic/{raw_model}"
        else:
            resolved_model = raw_model
        client = OpenAI(api_key=resolved_api_key, base_url=resolved_base_url)
        self._client: OpenAI = client
        self._configured_base_url = resolved_base_url
        self._model = resolved_model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._telemetry = InferenceTelemetryTracker()
        _ping(client, resolved_model, max_tokens=max_tokens, configured_base_url=resolved_base_url,
              inference_profile=self._explicit_profile, temperature=temperature if self._explicit_profile else 0)

    @property
    def model(self) -> str:
        """Model identifier passed to completion requests."""
        return self._model

    @property
    def client(self) -> OpenAI:
        """OpenAI-compatible client used for completion requests."""
        return self._client

    @property
    def telemetry(self) -> InferenceTelemetryTracker:
        """Telemetry tracker recording call counts, tokens, and latencies."""
        return self._telemetry

    @property
    def inference_profile(self):
        """Return a documented policy only for both declared and actual endpoints."""
        if self._explicit_profile is not None:
            return inference_profiles.checked_inference_profile(self._explicit_profile, model=self._model,
                                                                base_url=str(self._client.base_url))
        return inference_profiles.resolve_inference_profile(
            self._model, self._configured_base_url, actual_base_url=str(self._client.base_url)
        )

    def run_json(self, request: StructuredOutputRequest) -> dict[str, Any]:
        """Call a JSON-schema structured-output endpoint and parse the response as JSON.

        Args:
            request: System/user prompts, JSON schema metadata, and retry log label.

        Returns:
            Parsed JSON object from the model response.
        """
        messages = [
            {"role": "system", "content": request.system},
            {"role": "user", "content": request.user},
        ]
        mode = self._explicit_profile["request_policy"]["structured_output"] if self._explicit_profile else "json_schema"
        output = {"response_format": {"type": "json_schema", "json_schema": {
            "name": request.schema_name, "strict": True, "schema": request.schema}}}
        if mode != "json_schema":
            output = {"response_format": {"type": "json_object"}} if mode == "json_object" else {}
            messages[0]["content"] += "\nReturn only a JSON object matching this schema (local validation; "                 "no provider-side schema enforcement is claimed):\n" + json.dumps(request.schema, sort_keys=True)
        last_exc: Exception | None = None
        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                print(
                    f"[{request.retry_label}] retry {attempt}/{self._max_retries} after: {type(last_exc).__name__}:"
                    f" {last_exc}",
                    flush=True,
                )
            start_time = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    **output,
                    **completion_request_parameters(
                        model=self._model,
                        base_url=str(self._client.base_url),
                        temperature=self._temperature,
                        max_tokens=self._max_tokens,
                        configured_base_url=self._configured_base_url,
                        inference_profile=self._explicit_profile,
                    ),
                )
                duration_s = time.perf_counter() - start_time
                choices = getattr(resp, "choices", None) or []
                assert choices, (
                    f"Model {self._model!r} returned HTTP 200 with no choices "
                    "(content filter / guardrail / rate-limit response with empty body)."
                )
                strict_user = self._explicit_profile is not None and self._explicit_profile["origin"] == "user_defined"
                text = choices[0].message.content if request.parse_json or strict_user else _extract_response_text(choices[0].message)
                assert text, (
                    f"Model {self._model!r} returned an empty structured-outputs envelope. "
                    "Verify the endpoint/model supports response_format=json_schema."
                )

                if strict_user:
                    from isaaclab_arena.agentic_environment_generation.spec_wire_adapter import SpecWireAdapter
                    parsed = SpecWireAdapter.parse_json(text)
                    _validate_structured_value(parsed, request.schema)
                    if request.parse_json:
                        parsed = request.parse_json(text)
                else:
                    parsed = request.parse_json(text) if request.parse_json else json.loads(text, strict=False)

                # Record successful call telemetry
                usage = getattr(resp, "usage", None)
                p_tokens_raw = getattr(usage, "prompt_tokens", 0) if usage else 0
                c_tokens_raw = getattr(usage, "completion_tokens", 0) if usage else 0
                p_tokens = int(p_tokens_raw) if isinstance(p_tokens_raw, (int, float)) else 0
                c_tokens = int(c_tokens_raw) if isinstance(c_tokens_raw, (int, float)) else 0
                t_tokens = p_tokens + c_tokens
                self._telemetry.calls.append(
                    InferenceCallMetrics(
                        stage=request.retry_label,
                        prompt_tokens=p_tokens,
                        completion_tokens=c_tokens,
                        total_tokens=t_tokens,
                        duration_s=duration_s,
                        model=self._model,
                        success=True,
                    )
                )

                return parsed
            except Exception as exc:
                duration_s = time.perf_counter() - start_time
                self._telemetry.calls.append(
                    InferenceCallMetrics(
                        stage=request.retry_label,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=0,
                        duration_s=duration_s,
                        model=self._model,
                        success=False,
                    )
                )
                last_exc = exc
                if isinstance(exc, APIStatusError) and exc.status_code in (400, 401, 403, 404, 422):
                    # Repeating identical invalid requests cannot repair their contract.
                    break
        raise RuntimeError(
            f"Model {self._model!r} failed {request.retry_label} after {attempt + 1} attempts. Last error: {last_exc}"
        ) from last_exc

    def multimodal_chat(self, prompt: str, images: dict[str, Any]) -> str:
        """Call multimodal LLM with text prompt and images.

        Args:
            prompt: Inspection / critique instructions.
            images: Mapping of camera name to raw bytes or file path.

        Returns:
            Raw text/JSON completion from the model.
        """
        content_payload: list[dict[str, Any]] = [{"type": "text", "text": prompt}]
        for cam_name, img_data in images.items():
            if isinstance(img_data, bytes):
                b64_str = base64.b64encode(img_data).decode("utf-8")
                content_payload.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })
            elif isinstance(img_data, (str, os.PathLike)):
                with open(img_data, "rb") as f:
                    b64_str = base64.b64encode(f.read()).decode("utf-8")
                content_payload.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:image/png;base64,{b64_str}"},
                })

        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": content_payload}],
            **({"response_format": {"type": "json_object"}} if not self._explicit_profile
               or self._explicit_profile["request_policy"]["multimodal_output"] == "json_object" else {}),
            **completion_request_parameters(
                model=self._model,
                base_url=str(self._client.base_url),
                temperature=self._temperature,
                max_tokens=self._max_tokens,
                configured_base_url=self._configured_base_url,
                        inference_profile=self._explicit_profile,
            ),
        )
        choice = resp.choices[0] if resp.choices else None
        text = (choice.message.content if choice and choice.message else "") or ""
        text = text.strip()
        if text.startswith("```json"):
            text = text[len("```json") :].strip()
        elif text.startswith("```"):
            text = text[len("```") :].strip()
        if text.endswith("```"):
            text = text[:-3].strip()
        return text


def _validate_structured_value(value, schema):
    """Validate the harness-generated JSON Schema subset locally, without coercion.

    Unknown semantic keywords fail closed. This is not a provider compatibility
    assertion or a replacement for subsequent Arena domain validation.
    """
    import re
    annotations = {"title", "description", "default", "examples", "$schema", "$defs", "deprecated", "readOnly"}
    supported = {"$ref", "type", "anyOf", "oneOf", "allOf", "properties", "required", "additionalProperties",
                 "items", "prefixItems", "minItems", "maxItems", "minLength", "maxLength", "pattern",
                 "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "enum", "const"} | annotations

    def visit(item, node, depth=0):
        if depth > 128 or type(node) is not dict or set(node) - supported:
            raise ValueError("Unsupported local structured-output schema")
        if "$ref" in node:
            ref = node["$ref"]
            if type(ref) is not str or not ref.startswith("#/$defs/") or "/" in ref[8:]:
                raise ValueError("Unsupported local schema reference")
            visit(item, schema["$defs"][ref[8:]], depth + 1)
        for union in ("anyOf", "oneOf", "allOf"):
            if union in node:
                matches = 0
                for branch in node[union]:
                    try:
                        visit(item, branch, depth + 1)
                        matches += 1
                    except ValueError:
                        pass
                if (union == "anyOf" and not matches or union == "oneOf" and matches != 1
                        or union == "allOf" and matches != len(node[union])):
                    raise ValueError("Structured output does not match schema union")
        kinds = {"object": (dict,), "array": (list,), "string": (str,), "integer": (int,),
                 "number": (int, float), "boolean": (bool,), "null": (type(None),)}
        kind = node.get("type")
        if kind is not None and (kind not in kinds or type(item) not in kinds[kind]):
            raise ValueError("Structured output schema type mismatch")
        if "enum" in node and item not in node["enum"] or "const" in node and item != node["const"]:
            raise ValueError("Structured output enum mismatch")
        if type(item) is dict:
            props = node.get("properties", {})
            if set(node.get("required", [])) - set(item):
                raise ValueError("Structured output missing fields")
            for key, child in item.items():
                child_schema = props.get(key, node.get("additionalProperties", True))
                if child_schema is False:
                    raise ValueError("Structured output unexpected field")
                if child_schema is not True:
                    visit(child, child_schema, depth + 1)
        elif type(item) is list:
            if not node.get("minItems", 0) <= len(item) <= node.get("maxItems", 100000):
                raise ValueError("Structured output array bounds")
            prefix = node.get("prefixItems", [])
            for index, child in enumerate(item):
                child_schema = prefix[index] if index < len(prefix) else node.get("items", {})
                visit(child, child_schema, depth + 1)
        elif type(item) is str:
            if (not node.get("minLength", 0) <= len(item) <= node.get("maxLength", 1024 * 1024)
                    or "pattern" in node and re.search(node["pattern"], item) is None):
                raise ValueError("Structured output string bounds")
        elif type(item) in (int, float):
            if ("minimum" in node and item < node["minimum"] or "maximum" in node and item > node["maximum"]
                    or "exclusiveMinimum" in node and item <= node["exclusiveMinimum"]
                    or "exclusiveMaximum" in node and item >= node["exclusiveMaximum"]):
                raise ValueError("Structured output numeric bounds")
    visit(value, schema)


def build_strict_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Return ``model_cls``'s JSON schema munged for OpenAI strict mode."""
    schema = copy.deepcopy(model_cls.model_json_schema())
    _apply_strict_constraints(schema)
    return schema


def _ping(client: OpenAI, model: str, *, max_tokens: int = 8, configured_base_url: str | None = None,
          inference_profile: dict | None = None, temperature: float = 0) -> str:
    """Smoke-test the endpoint + API key + model with a minimal request.

    Args:
        client: An OpenAI-compatible client (typically ``openai.OpenAI``).
        model: Model identifier forwarded to
            ``client.chat.completions.create(model=...)``.
        max_tokens: Configured completion ceiling; the Astra ping cannot exceed it.
        configured_base_url: Original endpoint literal, before SDK normalization.

    Returns:
        The model's response text.
    """
    # TODO(qianl): wrap with transient-error retry.
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Respond with exactly: OK"}],
        **completion_request_parameters(
            model=model,
            base_url=str(client.base_url),
            temperature=temperature,
            max_tokens=max_tokens,
            ping=True,
            configured_base_url=configured_base_url,
            inference_profile=inference_profile,
        ),
    )
    choices = getattr(resp, "choices", None) or []
    assert choices, (
        f"ping to model {model!r} returned HTTP 200 with no choices "
        "(content filter / guardrail / rate-limit response with empty body)."
    )
    return choices[0].message.content or ""


def _apply_strict_constraints(node: dict | list) -> None:
    """Recursively apply OpenAI strict-mode constraints to a JSON-schema node."""
    if isinstance(node, dict):
        if node.get("type") == "object" and "properties" in node:
            node["additionalProperties"] = False
            node["required"] = list(node["properties"].keys())
        # Strict mode forbids ``default`` keys (every field is required, so
        # defaults can never apply). Drop them defensively at every level.
        node.pop("default", None)
        for v in node.values():
            _apply_strict_constraints(v)
    elif isinstance(node, list):
        for v in node:
            _apply_strict_constraints(v)


def _extract_response_text(message: ChatCompletionMessage) -> str | None:
    """Pull structured-output text from a chat-completion message and strip markdown fences."""
    raw = message.content or getattr(message, "reasoning_content", None)
    if not raw:
        return None
    raw = raw.strip()
    # Strip markdown ```json ... ``` or ``` ... ``` code blocks commonly emitted by Anthropic / OpenRouter
    if raw.startswith("```"):
        lines = raw.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    return raw
