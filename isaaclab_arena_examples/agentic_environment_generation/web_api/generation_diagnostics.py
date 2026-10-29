# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Classify private SDK failures into closed codes without retaining provider text."""

from isaaclab_arena.agentic_environment_generation.workbench.generation_diagnostics import checked_diagnostic


class SafeGenerationFailure(ValueError):
    """Trusted generation condition with a static code, never a provider message."""

    def __init__(self, code):
        messages = {
            "required_retrieval_unavailable": "Required graph retrieval unavailable",
            "invalid_specification": "Invalid Arena environment specification",
        }
        if code not in messages:
            raise ValueError("Invalid trusted generation failure")
        self.code = code
        super().__init__(messages[code])


def _rejection_code(body):
    """Map only plain SDK body fields to closed static codes; retain no payload."""
    if type(body) is not dict:
        return "provider_request_rejected"
    body = body.get("error", body)
    if type(body) is not dict:
        return "provider_request_rejected"
    code = body.get("code")
    message = body.get("message")
    # Never coerce objects, stringify exceptions, or scan unbounded provider text.
    code = code if type(code) is str and len(code) <= 64 else ""
    message = message if type(message) is str and len(message) <= 8192 else ""
    classified = {
        "invalid_json_schema": "provider_schema_rejected",
        "unsupported_parameter": "provider_parameter_unsupported",
        "unsupported_value": "provider_parameter_unsupported",
        "model_not_found": "provider_model_unavailable",
    }.get(code, "provider_request_rejected")
    if classified == "provider_request_rejected":
        if message.startswith("Invalid schema for response_format "):
            classified = "provider_schema_rejected"
        elif message.startswith(("Unsupported parameter: ", "Unsupported value: ")):
            classified = "provider_parameter_unsupported"
    if classified == "provider_schema_rejected":
        keywords = {
            "'minItems' is not permitted.": "provider_schema_min_items_unsupported",
            "'maxItems' is not permitted.": "provider_schema_max_items_unsupported",
            "'prefixItems' is not permitted.": "provider_schema_prefix_items_unsupported",
        }
        matches = [value for signature, value in keywords.items() if signature in message]
        # Multiple known findings are still schema rejection, not one exact issue.
        if len(matches) == 1:
            classified = matches[0]
    return classified


def classify_failure(error, stage):
    """Project installed SDK types/statuses through a bounded, cycle-safe cause chain."""
    try:
        import openai
    except ImportError:
        openai = None

    codes = (
        (
            (openai.AuthenticationError, "provider_authentication"),
            (openai.PermissionDeniedError, "provider_permission"),
            (openai.RateLimitError, "provider_rate_limit"),
            (openai.NotFoundError, "provider_model_unavailable"),
            (openai.BadRequestError, "provider_request_rejected"),
            (openai.UnprocessableEntityError, "provider_request_rejected"),
            (openai.APITimeoutError, "provider_timeout"),
            (openai.APIConnectionError, "provider_connection"),
        )
        if openai is not None
        else ()
    )
    statuses = {
        401: "provider_authentication",
        403: "provider_permission",
        429: "provider_rate_limit",
        404: "provider_model_unavailable",
        400: "provider_request_rejected",
        422: "provider_request_rejected",
        408: "provider_timeout",
    }
    code = "internal_error"
    seen = set()
    for _ in range(8):
        if error is None or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, SafeGenerationFailure):
            code = error.code
            break
        if isinstance(error, ImportError):
            code = "dependency_unavailable"
            break
        matched = next((value for kind, value in codes if isinstance(error, kind)), None)
        if matched is not None:
            code = matched
            if (
                code == "provider_request_rejected"
                and type(error.status_code) is int
                and error.status_code in (400, 422)
            ):
                code = _rejection_code(error.body)
            break
        if openai is not None and isinstance(error, openai.APIStatusError) and type(error.status_code) is int:
            fallback = "provider_request_rejected" if 400 <= error.status_code < 500 else "internal_error"
            code = statuses.get(error.status_code, fallback)
            if error.status_code in (400, 422):
                code = _rejection_code(error.body)
            break
        error = error.__cause__ if error.__cause__ is not None else error.__context__
    return checked_diagnostic({"schema_version": 1, "code": code, "stage": stage})
