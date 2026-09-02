# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""OpenAI-compatible structured-output inference backend for agent inference steps."""

from __future__ import annotations

import base64
import copy
import json
import os
from pathlib import Path
import time
from dataclasses import dataclass, field
from typing import Any

from openai import OpenAI
from openai.types.chat import ChatCompletionMessage
from pydantic import BaseModel


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
            try:
                with open(p, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#") and "=" in line:
                            key, val = line.split("=", 1)
                            key = key.strip()
                            val = val.strip().strip("\"'")
                            if key not in os.environ:
                                os.environ[key] = val
            except Exception:
                pass


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


class InferenceBackend:
    """Shared LLM JSON-schema runner with retry and tolerant JSON parsing."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 4096,
        max_retries: int = 3,
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
        """
        assert (
            0 <= max_retries < MAX_RETRIES_LIMIT
        ), f"max_retries must be in [0, {MAX_RETRIES_LIMIT}), got {max_retries}"
        _load_dotenv_if_present()
        resolved_api_key = (
            api_key
            or os.getenv("OPENROUTER_API_KEY")
            or os.getenv("NV_API_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
        )
        assert resolved_api_key, "API key required: set OPENROUTER_API_KEY, NV_API_KEY, OPENAI_API_KEY, or pass api_key."

        is_openrouter = (
            resolved_api_key.startswith("sk-or-")
            or bool(os.getenv("OPENROUTER_API_KEY"))
            or (base_url is not None and "openrouter.ai" in base_url)
            or bool(os.getenv("OPENROUTER_BASE_URL"))
        )
        default_endpoint = "https://openrouter.ai/api/v1" if is_openrouter else DEFAULT_BASE_URL
        default_model_id = (os.getenv("OPENROUTER_MODEL") or DEFAULT_OPENROUTER_MODEL) if is_openrouter else DEFAULT_MODEL

        resolved_base_url = (
            base_url
            or os.getenv("OPENROUTER_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or os.getenv("NV_BASE_URL")
            or os.getenv("BASE_URL")
            or default_endpoint
        )
        raw_model = (
            model
            or (os.getenv("OPENROUTER_MODEL") if is_openrouter else None)
            or os.getenv("OPENAI_MODEL")
            or os.getenv("NV_MODEL")
            or default_model_id
        )
        if is_openrouter and raw_model in ANTHROPIC_MODELS:
            resolved_model = ANTHROPIC_MODELS[raw_model]
        elif is_openrouter and raw_model.startswith("claude-") and not raw_model.startswith("anthropic/"):
            resolved_model = f"anthropic/{raw_model}"
        else:
            resolved_model = raw_model
        client = OpenAI(api_key=resolved_api_key, base_url=resolved_base_url)
        self._client: OpenAI = client
        self._model = resolved_model
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._max_retries = max_retries
        self._telemetry = InferenceTelemetryTracker()
        _ping(client, resolved_model)

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
        last_exc: Exception | None = None
        for attempt in range(1 + self._max_retries):
            if attempt > 0:
                print(f"[{request.retry_label}] retry {attempt}/{self._max_retries} after: {type(last_exc).__name__}: {last_exc}", flush=True)
            start_time = time.perf_counter()
            try:
                resp = self._client.chat.completions.create(
                    model=self._model,
                    messages=messages,
                    response_format={
                        "type": "json_schema",
                        "json_schema": {
                            "name": request.schema_name,
                            "strict": True,
                            "schema": request.schema,
                        },
                    },
                    temperature=self._temperature,
                    max_tokens=self._max_tokens,
                )
                duration_s = time.perf_counter() - start_time
                choices = getattr(resp, "choices", None) or []
                assert choices, (
                    f"Model {self._model!r} returned HTTP 200 with no choices "
                    "(content filter / guardrail / rate-limit response with empty body)."
                )
                text = _extract_response_text(choices[0].message)
                assert text, (
                    f"Model {self._model!r} returned an empty structured-outputs envelope. "
                    "Verify the endpoint/model supports response_format=json_schema."
                )

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

                # ``strict=False`` lets json.loads accept unescaped control characters
                # (e.g. literal tabs) inside JSON strings — DeepSeek-v4-flash is known
                # to emit these.
                return json.loads(text, strict=False)
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
        raise RuntimeError(
            f"Model {self._model!r} failed {request.retry_label} after "
            f"{1 + self._max_retries} attempts. Last error: {last_exc}"
        ) from last_exc

    def multimodal_chat(
        self, prompt: str, images: dict[str, Any]
    ) -> str:
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
            response_format={"type": "json_object"},
            temperature=self._temperature,
            max_tokens=self._max_tokens,
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


def build_strict_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    """Return ``model_cls``'s JSON schema munged for OpenAI strict mode."""
    schema = copy.deepcopy(model_cls.model_json_schema())
    _apply_strict_constraints(schema)
    return schema


def _ping(client: OpenAI, model: str) -> str:
    """Smoke-test the endpoint + API key + model with a minimal request.

    Args:
        client: An OpenAI-compatible client (typically ``openai.OpenAI``).
        model: Model identifier forwarded to
            ``client.chat.completions.create(model=...)``.

    Returns:
        The model's response text.
    """
    # TODO(qianl): wrap with transient-error retry.
    resp = client.chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": "Respond with exactly: OK"}],
        temperature=0,
        max_tokens=8,
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
