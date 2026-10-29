# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Process-local SDK admission, not actual billing metering or execution authority.

Only chat-completion SDK attempts through this adapter are guarded. Deadlines
admit calls; they do not cancel in-flight HTTP. There is no durable accounting
or guard for direct urllib fallbacks. Importing this module loads no SDK/backend.
"""

import base64
import hashlib
import math
import threading
import time
from contextlib import contextmanager
from decimal import Decimal
from email.utils import parsedate_to_datetime

from .accounting import _usd_units, checked_workflow_accounting
from .request_envelope import RequestEnvelope


class CallAllowance:
    """Share a positive call ceiling and absolute monotonic deadline across contexts.

    Args:
        max_calls: Positive integer count of admitted SDK attempts, including failures.
        deadline: Absolute time.monotonic() deadline; infinity preserves legacy no-expiry.
        max_tokens: Optional nonnegative operation token budget; requires both other accounting fields.
        cost_ceiling_usd: Optional decimal USD string, up to 18 integer and nine fractional digits.
        per_call_bound: Complete versioned trusted total-call attestation, never derived from the budget.

    Charges are conservative upper bounds with no refunds, not observed consumption.
    Absent accounting retains count-only behavior and unknown token/cost counters.
    """

    def __init__(self, *, max_calls: int, deadline: float, max_tokens=None, cost_ceiling_usd=None, per_call_bound=None):
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("max_calls must be a positive integer")
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or math.isnan(deadline):
            raise ValueError("deadline must be an absolute monotonic time")
        self._max_calls = max_calls
        self._deadline = deadline
        self._attempted_calls = 0
        self._lock = threading.Lock()
        self._bound = None
        self._charged_tokens = self._charged_cost = 0
        self.provider_records = []
        self.retain_provider_phase = None
        if type(per_call_bound) is dict and per_call_bound.get("version") == 2:
            self._bound = checked_workflow_accounting(per_call_bound)
            if max_tokens is not None or cost_ceiling_usd is not None:
                raise ValueError("Accounting-only allowance cannot contain token/cost caps")
        elif any(v is not None for v in (max_tokens, cost_ceiling_usd, per_call_bound)):
            if type(max_tokens) is not int or max_tokens < 0:
                raise ValueError("Complete token/cost allowance required")
            self._cost_ceiling = _usd_units(cost_ceiling_usd)
            self._bound = checked_workflow_accounting(per_call_bound)
            self._max_tokens = max_tokens
            self._call_cost = _usd_units(self._bound["max_cost_usd"])

    @property
    def token_cost_bounded(self):
        """Whether total admission is bounded conditional on the trusted attestation."""
        return self._bound is not None and self._bound["version"] == 1

    @property
    def accounting_only(self):
        """Whether usage is recorded without a synthetic price or monetary/token veto."""
        return self._bound is not None and self._bound["version"] == 2

    @property
    def charged_tokens(self):
        with self._lock:
            return self._charged_tokens if self.token_cost_bounded else None

    @property
    def charged_cost_usd(self):
        with self._lock:
            if not self.token_cost_bounded:
                return None
            whole, fraction = divmod(self._charged_cost, 10**9)
            return Decimal(f"{whole}.{fraction:09d}")

    @property
    def max_calls(self):
        return self._max_calls

    @property
    def deadline(self):
        return self._deadline

    @property
    def attempted_calls(self):
        with self._lock:
            return self._attempted_calls

    def charge(self):
        """Admit and charge before SDK invocation; denied calls and refunds are absent."""
        with self._lock:
            if time.monotonic() >= self._deadline:
                raise ValueError("Generation call deadline exhausted")
            if self._attempted_calls >= self._max_calls:
                raise ValueError("Generation call budget exhausted")
            if self.token_cost_bounded:
                if self._charged_tokens + self._bound["max_tokens"] > self._max_tokens:
                    raise ValueError("Generation token budget exhausted")
                if self._charged_cost + self._call_cost > self._cost_ceiling:
                    raise ValueError("Generation cost budget exhausted")
                self._charged_tokens += self._bound["max_tokens"]
                self._charged_cost += self._call_cost
            self._attempted_calls += 1


_patch_lock = threading.Lock()
_managed_active = False


def retryable_http_failure(status, code):
    """Distinguish transient transport statuses from permission and quota failures."""
    return (status in (408, 429) or (type(status) is int and 500 <= status <= 599)) and code not in (
        "insufficient_quota",
        "billing_hard_limit_reached",
    )


def _provider_error(exc):
    from openai import APIConnectionError, APITimeoutError

    status, body = getattr(exc, "status_code", None), getattr(exc, "body", None)
    code = body.get("code") if type(body) is dict else None
    return dict(
        kind=type(exc).__name__,
        status=status,
        code=code if type(code) is str else None,
        retryable=isinstance(exc, (APIConnectionError, APITimeoutError)) or retryable_http_failure(status, code),
        request_id=getattr(exc, "request_id", None),
    )


def _retain_phase(allowance, phase):
    if allowance.retain_provider_phase is not None:
        try:
            allowance.retain_provider_phase(phase, allowance.provider_records[-1])
        except Exception as exc:
            allowance.provider_records[-1]["retention_error"] = dict(phase=phase, kind=type(exc).__name__)
            raise


def _retain_request(allowance, raw):
    if allowance.accounting_only:
        allowance.provider_records[-1]["serialized_request"] = raw.decode("utf-8")
        _retain_phase(allowance, "request")


def _retry_after_deadline(value, received_at):
    if value is None:
        return None
    try:
        delay = float(value)
    except ValueError:
        try:
            delay = parsedate_to_datetime(value).timestamp() - received_at
        except (ValueError, TypeError, OverflowError):
            return None
    return received_at + max(0, delay) if math.isfinite(delay) else None


def _retain_http_response(allowance, response):
    response.read()
    raw = response.content
    received_at = time.time()
    retry_after = response.headers.get("retry-after")
    allowance.provider_records[-1]["http_response"] = dict(
        status_code=response.status_code,
        request_id=response.headers.get("x-request-id"),
        received_at=received_at,
        retry_after=retry_after,
        retry_not_before_unix=_retry_after_deadline(retry_after, received_at),
        body_base64=base64.b64encode(raw).decode("ascii"),
        body_utf8=raw.decode("utf-8", errors="replace"),
        body_sha256=hashlib.sha256(raw).hexdigest(),
    )
    _retain_phase(allowance, "response")


def _complete_recorded(completion, kwargs, pending, allowance):
    """Keep actual SDK responses and unknown costs in the existing call allowance."""
    pending.admitted = True
    record = None
    if allowance.accounting_only:
        record = dict(
            request=kwargs,
            dispatched=False,
            response=None,
            transport_error=None,
            usage=None,
            cost_usd=None,
            cost_basis="unknown_no_price_attestation",
        )
        allowance.provider_records.append(record)
    try:
        response = completion(**kwargs)
        if record is not None:
            record["response"] = response.model_dump(mode="json")
            record["usage"] = response.usage.model_dump(mode="json") if response.usage else None
        return response
    except Exception as exc:
        if record is not None:
            record["transport_error"] = _provider_error(exc)
        raise
    finally:
        try:
            if record is not None and getattr(pending, "raw", None) is not None:
                record["serialized_request"] = pending.raw.decode("utf-8")
                _retain_phase(allowance, "complete")
        finally:
            pending.admitted = False


def managed_inference_active(backend=None):
    """Identify managed transport, including a retained backend after its context closed."""
    client = getattr(backend, "client", None)
    return _managed_active or getattr(client, "_arena_workflow_managed", False) is True


@contextmanager
def bounded_client(
    config,
    *,
    allowance: CallAllowance,
    strict_model_binding: bool = True,
    request_envelope=None,
    send_guard=None,
):
    """Install bounded transport before backend construction in an isolated worker.

    Args:
        config: Explicit api_key, base_url and model; values are frozen on entry.
        allowance: Caller-owned shared allowance, never reset or refunded on exit.
        strict_model_binding: Reject mismatches; only the legacy wrapper disables this
            to preserve its historical configured-model override.
        request_envelope: Optional frozen v1 callable contract. This is not a
            persisted profile/grant binding or verification of provider prices.
        send_guard: Optional current-authority check on final bytes before each
            physical send. Requires an envelope; never called after transmission.

    Overlapping global factory patches are rejected rather than queued. The
    caller must disable backend dotenv loading and pass its explicit profile.
    Backend semantic retries are unchanged; SDK transport retries are zero.
    With an envelope, public copy/with_options cloning is unsupported, including
    default and same-transport clones; without one the legacy SDK API is unchanged.
    This guards the adapter's callable surface, not arbitrary Python execution:
    deliberate guard replacement, unbound SDK calls or separately constructed
    clients are outside the contract. It is not a credential or process sandbox.
    """
    global _managed_active
    if not isinstance(allowance, CallAllowance):
        raise TypeError("allowance must be a CallAllowance")
    if send_guard is not None and (not callable(send_guard) or request_envelope is None):
        raise ValueError("Final send authority requires an executable envelope")
    api_key, base_url, model = (config[name] for name in ("api_key", "base_url", "model"))
    if not all(isinstance(value, str) and value for value in (api_key, base_url, model)):
        raise ValueError("Explicit provider configuration required")
    if allowance._bound is not None:
        if not strict_model_binding:
            raise ValueError("Workflow accounting requires strict model binding")
        checked_workflow_accounting(allowance._bound, model=model, endpoint=base_url)
    if request_envelope is not None:
        if type(request_envelope) is not RequestEnvelope:
            raise ValueError("frozen request envelope required")
        request_envelope.check_binding(model=model, endpoint=base_url, accounting=allowance._bound)
    if not _patch_lock.acquire(blocking=False):
        raise RuntimeError("Overlapping bounded client contexts are forbidden")
    try:
        _managed_active = bool(strict_model_binding)
        from openai import DefaultHttpxClient, OpenAI, OpenAIError

        from isaaclab_arena.agentic_environment_generation import inference_backend

        # Some runtimes vendor HTTPX under a different module name.
        timeout = min(180, max(0.001, allowance.deadline - time.monotonic())) if allowance.accounting_only else 45
        with DefaultHttpxClient(follow_redirects=False, trust_env=False, timeout=timeout) as transport:
            with OpenAI(
                api_key=api_key,
                base_url=base_url,
                http_client=transport,
                timeout=timeout,
                max_retries=0,
            ) as client:
                client._arena_workflow_managed = _managed_active
                if request_envelope is not None:
                    # Public SDK clones do not inherit these instance-local guards.
                    # Reject both aliases, even for default/same-transport copies.
                    def reject_clone(*args, **kwargs):
                        raise ValueError("request envelope client cloning is unsupported")

                    client.copy = reject_clone
                    client.with_options = reject_clone
                    # SDK build merges extra JSON/headers and serializes actual bytes.
                    # HTTPX request hooks run after SDK preparation/auth, immediately
                    # before transport. Validate both, and allow one physical send
                    # per charged create even if an SDK auth/retry path changes.
                    build_request = client._build_request
                    pending = threading.local()

                    def build(*args, **kwargs):
                        if not getattr(pending, "admitted", False):
                            raise ValueError("request envelope requires guarded completion")
                        request = build_request(*args, **kwargs)
                        request_envelope.check_http(request, api_key=api_key)
                        pending.request, pending.stream, pending.raw = (
                            request,
                            request.stream,
                            request.content,
                        )
                        return request

                    client._build_request = build

                    def before_send(request):
                        try:
                            if not getattr(pending, "admitted", False):
                                raise ValueError("request envelope unadmitted send")
                            request_envelope.check_binding(
                                model=model,
                                endpoint=base_url,
                                accounting=allowance._bound,
                            )
                            if (
                                request is not pending.request
                                or request.stream is not pending.stream
                                or request.content != pending.raw
                                or list(request.stream) != [pending.raw]
                            ):
                                raise ValueError("request envelope serialized bytes changed")
                            request_envelope.check_http(request, api_key=api_key)
                            if time.monotonic() >= allowance.deadline:
                                raise ValueError("Generation send deadline exhausted")
                            _retain_request(allowance, pending.raw)
                            if send_guard is not None:
                                send_guard(request)
                            if time.monotonic() >= allowance.deadline:
                                raise ValueError("Generation send authority expired")
                            if allowance.accounting_only:
                                allowance.provider_records[-1]["dispatched"] = True
                            pending.admitted = False
                        except ValueError:
                            raise OpenAIError("request envelope rejected before transport") from None

                    transport.event_hooks["request"].append(before_send)
                    if allowance.accounting_only:
                        transport.event_hooks["response"].append(
                            lambda response: _retain_http_response(allowance, response)
                        )
                completion = client.chat.completions.create

                def complete(*args, **kwargs):
                    # Legacy callers historically override the backend's normalized alias.
                    if strict_model_binding and kwargs.get("model", model) != model:
                        raise ValueError("Bounded client model binding mismatch")
                    kwargs["model"] = model
                    if request_envelope is not None:
                        request_envelope.check_binding(model=model, endpoint=base_url, accounting=allowance._bound)
                        kwargs = request_envelope.copy_arguments(args, kwargs)
                        request_envelope.check_body(kwargs)
                    allowance.charge()
                    if request_envelope is None:
                        return completion(*args, **kwargs)
                    return _complete_recorded(completion, kwargs, pending, allowance)

                client.chat.completions.create = complete
                original = inference_backend.OpenAI
                inference_backend.OpenAI = lambda **kwargs: client
                try:
                    yield client
                finally:
                    inference_backend.OpenAI = original
    finally:
        _managed_active = False
        _patch_lock.release()
