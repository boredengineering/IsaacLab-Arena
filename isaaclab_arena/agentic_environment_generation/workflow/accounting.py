# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Pure accounting attestations; no transport construction or effect authority."""

import re


def _usd_units(value):
    """Parse explicit decimal USD into exact integer nano-USD, never binary floats."""
    if type(value) is not str or re.fullmatch(r"(?:0|[1-9][0-9]{0,17})(?:\.[0-9]{1,9})?", value) is None:
        raise ValueError("Invalid exact USD amount")
    whole, _, fraction = value.partition(".")
    return int(whole) * 10**9 + int(fraction.ljust(9, "0"))


def checked_workflow_accounting(value, *, model=None, endpoint=None):
    """Validate a trusted attestation of total per-call tokens and USD, including images.

    This is a composition assertion, not provider verification or a price estimate.
    The bound must cover every possible request admitted for this model/endpoint,
    including input, output, images, failed calls and provider-side billing rules.
    USD strings allow up to nine fractional digits; an explicitly attested free
    call may have zero cost, but unknown cost is never interpreted as free.
    """
    if (
        type(value) is not dict
        or set(value) != {"version", "attested", "model", "endpoint", "max_tokens", "max_cost_usd"}
        or type(value["version"]) is not int
        or value["version"] not in (1, 2)
        or any(type(value[k]) is not str or not value[k] for k in ("model", "endpoint"))
        or (model is not None and value["model"] != model)
        or (endpoint is not None and value["endpoint"] != endpoint)
    ):
        raise ValueError("Invalid workflow accounting attestation")
    if value["version"] == 2:
        if value["attested"] is not False or value["max_tokens"] is not None or value["max_cost_usd"] is not None:
            raise ValueError("Accounting-only policy requires explicit unknown token/cost ceilings")
        return dict(value)
    if value["attested"] is not True or type(value["max_tokens"]) is not int or value["max_tokens"] <= 0:
        raise ValueError("Invalid workflow accounting attestation")
    _usd_units(value["max_cost_usd"])
    return dict(value)
