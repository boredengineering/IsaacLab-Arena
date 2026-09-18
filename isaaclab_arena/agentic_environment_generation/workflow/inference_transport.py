# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Process-local SDK call admission, not token/cost metering or execution authority.

Only chat-completion SDK attempts through this adapter are guarded. Deadlines
admit calls; they do not cancel in-flight HTTP. There is no durable accounting
or guard for direct urllib fallbacks. Importing this module loads no SDK/backend.
"""

import math
import threading
import time
from contextlib import contextmanager


class CallAllowance:
    """Share a positive call ceiling and absolute monotonic deadline across contexts.

    Args:
        max_calls: Positive integer count of admitted SDK attempts, including failures.
        deadline: Absolute time.monotonic() deadline; infinity preserves legacy no-expiry.
    """

    def __init__(self, *, max_calls: int, deadline: float):
        if type(max_calls) is not int or max_calls <= 0:
            raise ValueError("max_calls must be a positive integer")
        if isinstance(deadline, bool) or not isinstance(deadline, (int, float)) or math.isnan(deadline):
            raise ValueError("deadline must be an absolute monotonic time")
        self._max_calls = max_calls
        self._deadline = deadline
        self._attempted_calls = 0
        self._lock = threading.Lock()

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
            self._attempted_calls += 1


_patch_lock = threading.Lock()


@contextmanager
def bounded_client(config, *, allowance: CallAllowance, strict_model_binding: bool = True):
    """Install bounded transport before backend construction in an isolated worker.

    Args:
        config: Explicit api_key, base_url and model; values are frozen on entry.
        allowance: Caller-owned shared allowance, never reset or refunded on exit.
        strict_model_binding: Reject mismatches; only the legacy wrapper disables this
            to preserve its historical configured-model override.

    Overlapping global factory patches are rejected rather than queued. The
    caller must disable backend dotenv loading and pass its explicit profile.
    Backend semantic retries are unchanged; SDK transport retries are zero.
    """
    if not isinstance(allowance, CallAllowance):
        raise TypeError("allowance must be a CallAllowance")
    api_key, base_url, model = (config[name] for name in ("api_key", "base_url", "model"))
    if not all(isinstance(value, str) and value for value in (api_key, base_url, model)):
        raise ValueError("Explicit provider configuration required")
    if not _patch_lock.acquire(blocking=False):
        raise RuntimeError("Overlapping bounded client contexts are forbidden")
    try:
        from openai import DefaultHttpxClient, OpenAI

        from isaaclab_arena.agentic_environment_generation import inference_backend

        # Some runtimes vendor HTTPX under a different module name.
        with DefaultHttpxClient(follow_redirects=False, trust_env=False, timeout=45) as transport:
            with OpenAI(api_key=api_key, base_url=base_url, http_client=transport, timeout=45, max_retries=0) as client:
                completion = client.chat.completions.create

                def complete(*args, **kwargs):
                    # Legacy callers historically override the backend's normalized alias.
                    if strict_model_binding and kwargs.get("model", model) != model:
                        raise ValueError("Bounded client model binding mismatch")
                    kwargs["model"] = model
                    allowance.charge()
                    return completion(*args, **kwargs)

                client.chat.completions.create = complete
                original = inference_backend.OpenAI
                inference_backend.OpenAI = lambda **kwargs: client
                try:
                    yield client
                finally:
                    inference_backend.OpenAI = original
    finally:
        _patch_lock.release()
