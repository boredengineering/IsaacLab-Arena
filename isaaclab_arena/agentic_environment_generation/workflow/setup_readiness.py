# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline public setup inventory, never a live readiness receipt or authority."""

import hashlib
import ipaddress
import json
import re
from urllib.parse import urlsplit

from ..inference_profiles import FIXED_ENDPOINTS, checked_inference_profile

MAX_SELECTION_BYTES = 65536
MAX_SELECTION_DEPTH = 12
ROLES = ("generation", "assessment", "repair", "local_policy", "prior_read", "operational_db")
OUTCOMES = ("scene-only", "required-policy")
SOURCE_ROLES = dict(
    zip(
        ROLES,
        (
            "models.generation",
            "models.assessment",
            "models.repair",
            "policy.local",
            "databases.prior_read",
            "databases.operational",
        ),
    )
)


def _invalid():
    raise ValueError("Invalid public selection")


def _fields(value, allowed, required=()):
    if type(value) is not dict or not set(required) <= set(value) <= set(allowed):
        _invalid()
    return value


def _literal(value, limit=128):
    if type(value) is not str or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]{0," + str(limit - 1) + "}", value):
        _invalid()
    return value


def _endpoint(value, database=False, policy=False):
    if type(value) is not str or not re.fullmatch(r"[!-~]{1,512}", value) or any(c in value for c in "?#%@\\"):
        _invalid()
    url = urlsplit(value)
    schemes = (
        ("bolt", "bolt+s", "bolt+ssc", "neo4j", "neo4j+s", "neo4j+ssc")
        if database
        else ("tcp", "http", "https") if policy else ("http", "https")
    )
    if (
        url.scheme not in schemes
        or not url.hostname
        or url.username is not None
        or url.password is not None
        or url.port is not None
        and not 1 <= url.port <= 65535
        or database
        and url.path
        or url.netloc.endswith(":")
        or url.scheme == "tcp"
        and (url.port is None or url.path)
    ):
        _invalid()
    host = url.hostname
    assert host is not None, "endpoint host validated above"
    if ":" in host or re.fullmatch(r"[0-9.]+", host):
        ipaddress.ip_address(host)
    elif len(host) > 253 or not all(
        re.fullmatch(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?", label) for label in host.rstrip(".").split(".")
    ):
        _invalid()
    return value


def _credential(value, role):
    if value is None:
        return None
    _fields(value, ("alias", "source", "source_role", "public_id"), ("alias", "source", "source_role"))
    _literal(value["alias"])
    if (
        value["source"] not in ("private_file", "private_pipe", "named_environment", "none")
        or value["source_role"] != SOURCE_ROLES[role]
        or value["source"] == "none"
        and role != "local_policy"
    ):
        _invalid()
    if value.get("public_id") is not None:
        _literal(value["public_id"])
    return dict(value)


def _role(value, role):
    if value is None:
        return None
    database = role in ("prior_read", "operational_db")
    fields = ("provider", "endpoint", "credential")
    fields += ("database", "authentication", "tls") if database else ("model",)
    if role in FIXED_MODEL_ROLES:
        fields += ("inference_profile",)
    _fields(value, fields)
    result = dict.fromkeys(fields)
    result.update(value)
    for key in ("model", "database"):
        if result.get(key) is not None:
            _literal(result[key], 256 if key == "model" else 128)
    provider = result["provider"]
    if provider is not None and provider not in (
        ("neo4j",) if database else ("gr00t",) if role == "local_policy" else FIXED_ENDPOINTS
    ):
        _invalid()
    if result["endpoint"] is not None:
        _endpoint(result["endpoint"], database, role == "local_policy")
    result["credential"] = _credential(result["credential"], role)
    if database:
        if result["authentication"] not in (None, "basic", "bearer", "kerberos", "none"):
            _invalid()
        if result["tls"] not in (None, "none", "system_ca", "custom_ca", "self_signed"):
            _invalid()
    profile = result.get("inference_profile")
    if profile is not None:
        if any(result[key] is None for key in ("provider", "model", "endpoint")):
            _invalid()
        result["inference_profile"] = checked_inference_profile(
            profile, model=result["model"], base_url=result["endpoint"]
        )
        if profile["provider"] != provider or profile["endpoint"] != result["endpoint"]:
            _invalid()
    return result


FIXED_MODEL_ROLES = ("generation", "assessment", "repair")


def parse_selection(raw):
    """Validate bounded public JSON; missing roles/fields remain explicitly unresolved."""
    try:
        if type(raw) is not bytes or not 0 < len(raw) <= MAX_SELECTION_BYTES:
            _invalid()

        def pairs(items):
            result = {}
            for key, value in items:
                if key in result:
                    _invalid()
                result[key] = value
            return result

        def constant(_):
            _invalid()

        value = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)

        def depth(node, level=0):
            if level > MAX_SELECTION_DEPTH:
                _invalid()
            for child in node.values() if type(node) is dict else node if type(node) is list else ():
                depth(child, level + 1)

        depth(value)
        _fields(value, ("schema_version", "outcome", "roles"), ("schema_version", "outcome", "roles"))
        if type(value["schema_version"]) is not int or value["schema_version"] != 1 or value["outcome"] not in OUTCOMES:
            _invalid()
        _fields(value["roles"], ROLES)
        roles = {role: _role(value["roles"].get(role), role) for role in ROLES}
        aliases = {}
        for selected in roles.values():
            credential = selected and selected["credential"]
            if credential:
                identity = credential["source"], credential.get("public_id")
                if aliases.setdefault(credential["alias"], identity) != identity:
                    _invalid()
        return {"schema_version": 1, "outcome": value["outcome"], "roles": roles}
    except (ValueError, TypeError, RecursionError, UnicodeError):
        raise ValueError("Invalid public selection") from None


def _database_compatibility(selected, role):
    selected = selected or {}
    endpoint, tls, authentication = (selected.get(key) for key in ("endpoint", "tls", "authentication"))
    transport = "unresolved"
    if endpoint is not None and tls is not None:
        transport = "incompatible"
        try:
            url = urlsplit(endpoint)
            host = str(ipaddress.IPv4Address(url.hostname))
            # Mirrors installed_config.endpoint(bolt=True), without importing
            # credential/file machinery. This describes syntax, not reachability.
            if tls == "none" and type(url.port) is int and endpoint == f"bolt://{host}:{url.port}":
                transport = "compatible"
        except ValueError:
            pass
    credential = selected.get("credential")
    source = (
        "unresolved"
        if credential is None
        else "compatible" if credential["source"] == "private_file" else "incompatible"
    )
    return {
        "endpoint": endpoint,
        "database": selected.get("database"),
        "authentication": authentication,
        "tls": tls,
        "transport": transport,
        "auth": (
            "unresolved" if authentication is None else "compatible" if authentication == "basic" else "incompatible"
        ),
        "installed_credential_slot": "databases.operational" if role == "operational_db" else "databases.prior_read",
        "selection_credential": selected.get("credential"),
        "credential_source": source,
        "access": "not_checked",
    }


def _blockers(selection, rows, databases):
    outcome = selection["outcome"]
    required = [role for role in ROLES if rows[role]["required_for_outcome"]]
    blockers = []

    def add(code, owner, roles, action, outcomes=OUTCOMES):
        if outcome in outcomes:
            blockers.append(
                {"code": code, "owner": owner, "roles": list(roles), "outcomes": list(outcomes), "next_action": action}
            )

    unresolved = [role for role in required if rows[role]["public_selection"] == "unresolved"]
    if unresolved:
        add(
            "unresolved_selection",
            "operator_setup",
            unresolved,
            "Fill the unresolved public role fields; supply only aliases/source roles, never credential values.",
            (outcome,),
        )
    missing_profiles = [
        role for role in FIXED_MODEL_ROLES if not (selection["roles"][role] or {}).get("inference_profile")
    ]
    if missing_profiles:
        add(
            "model_request_profile",
            "operator_setup",
            missing_profiles,
            "Select an exact validated inference profile and request policy; documented support is not a live check.",
        )
    unsupported = [
        role
        for role in FIXED_MODEL_ROLES
        if (choice := selection["roles"][role])
        and choice["provider"]
        and choice["endpoint"]
        and choice["endpoint"] != FIXED_ENDPOINTS[choice["provider"]]
    ]
    if unsupported:
        add(
            "model_endpoint_adapter",
            "implementation_missing",
            unsupported,
            "Review a narrowly versioned adapter for the literal endpoint; do not switch endpoints or models"
            " implicitly.",
        )
    add(
        "private_role_bootstrap",
        "operator_setup",
        [*FIXED_MODEL_ROLES, "prior_read"],
        "Use explicit v3 role bindings and the private v2 setup pipe; no credential existence or live access is"
        " checked here. Repair currently requires explicit sharing of the generation profile and credential.",
    )
    add(
        "installed_execution",
        "implementation_missing",
        required,
        "Ordinary production execution remains unsupported. Preserve installed query-only access and guarded"
        " synthetic role/prior submission/control/readback; separately approve production composition, measured"
        " provider capabilities and campaign bounds before live work.",
        (outcome,),
    )
    incompatible = [role for role, row in databases.items() if "incompatible" in (row["transport"], row["auth"])]
    if incompatible:
        add(
            "database_adapter",
            "implementation_missing",
            incompatible,
            "Approve a compatible topology or implement a narrow transport/auth adapter; never downgrade TLS, replace"
            " endpoints or grant runtime DDL as a workaround.",
        )
    if databases["operational_db"]["credential_source"] == "incompatible":
        add(
            "database_credential_source",
            "implementation_missing",
            ("operational_db",),
            "Installed runtime reads its explicit private credential file; implement a reviewed source adapter or"
            " explicitly select that existing file path privately. Pipe input to setup is not runtime pipe support.",
        )
    add(
        "model_access_budget",
        "operator_setup",
        FIXED_MODEL_ROLES,
        "Arrange selected text/image/structured-output access, billing/quota and frozen request/pricing bounds; approve"
        " finite campaign ceilings including probes and retries.",
    )
    add(
        "runtime_identity_assets",
        "operator_setup",
        [],
        "Select the mapped non-root runtime, exact mounts, installed dependencies, cached assets and GPU allocation; do"
        " not start, install or download during inspection.",
    )
    add(
        "database_safety",
        "operator_setup",
        ("prior_read", "operational_db"),
        "Select prior-read versus operational permissions and pilot scope; obtain administrator-owned schema review and"
        " paired DB/artifact backup/restore evidence before writes.",
    )
    add(
        "private_operational_setup",
        "operator_setup",
        ("operational_db",),
        "After compatible query-only configuration is approved, use the existing private DB setup path; this public"
        " alias does not prove any credential file exists.",
    )
    add(
        "bounded_access_checks",
        "runtime_verification",
        [*FIXED_MODEL_ROLES, "prior_read", "operational_db"],
        "After adapter support and separate approval, perform bounded DB/access and actual text/structured-output/image"
        " checks under fixed paid suballocations; bind time and credential generation.",
    )
    add(
        "native_calibration",
        "runtime_verification",
        [],
        "Under separate approval verify runtime mounts/dependencies, native pose/contact/camera/settling and owned"
        " cleanup; offline configuration is not physical evidence.",
    )
    add(
        "policy_composition",
        "implementation_missing",
        ("local_policy",),
        "Join and isolated-test the owned policy worker, task/checkpoint/evaluator pins and per-reset prerequisites"
        " before required-policy admission.",
        ("required-policy",),
    )
    add(
        "policy_setup",
        "operator_setup",
        ("local_policy",),
        "Pin the GR00T served instance, checkpoint/processor/assets/task evaluator and an approved GPU co-residency or"
        " distinct-device topology.",
        ("required-policy",),
    )
    add(
        "policy_runtime_verification",
        "runtime_verification",
        ("local_policy",),
        "Separately approve and verify actual GR00T inference, action mapping, fresh reset prerequisites and GPU"
        " headroom; metadata alone is not policy readiness.",
        ("required-policy",),
    )
    add(
        "execution_approval",
        "operator_setup",
        required,
        "After implementation and measured checks, obtain a bounded approval packet with exact"
        " operation/profile/credential-generation bindings and ceilings; this report grants nothing.",
        (outcome,),
    )
    return blockers


def setup_readiness(raw=None):
    """Describe public selections without discovering or checking private/live state."""
    selection = (
        parse_selection(raw)
        if raw is not None
        else {"schema_version": 1, "outcome": "scene-only", "roles": dict.fromkeys(ROLES)}
    )
    digest = hashlib.sha256(
        json.dumps(selection, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    ).hexdigest()
    rows = {}
    for role, selected in selection["roles"].items():
        configured = selected is not None and all(
            value is not None for key, value in selected.items() if key != "inference_profile"
        )
        credential = selected and selected["credential"]
        shared = sorted(
            other
            for other, choice in selection["roles"].items()
            if other != role
            and credential
            and choice
            and choice["credential"]
            and choice["credential"]["alias"] == credential["alias"]
        )
        rows[role] = {
            "selection": selected,
            "required_for_outcome": role != "local_policy" or selection["outcome"] == "required-policy",
            "public_selection": "configured" if configured else "unresolved",
            "shared_alias_with": shared,
            "access": "not_checked",
            "capability": "not_checked",
            "execution": "not_authorized",
            "checked_at": None,
        }
    databases = {
        role: _database_compatibility(selection["roles"][role], role) for role in ("prior_read", "operational_db")
    }
    return {
        "schema_version": 1,
        "outcome": selection["outcome"],
        "selection": selection,
        "selection_sha256": digest,
        "execution_authorized": False,
        "credential_generation": "not_observed",
        "access_checked_at": None,
        "capability_checked_at": None,
        "roles": rows,
        "database_compatibility": databases,
        "installed_boundary": {
            "mode": "query-only",
            "execution_modes": {
                "query-only": "supported",
                "isolated-synthetic-execution-v1": "harness_only",
                "production": "unsupported",
            },
            "provider_bootstrap": "private_roles_v2",
            "db_transport": "Exact numeric IPv4 bolt://address:port only; no DNS, routing or TLS support.",
            "db_authentication": "basic",
            "runtime_credential_slot": "databases.operational",
            "admin_credential_slot": "databases.operational",
            "prior_read_credential_slot": "databases.prior_read",
            "prior_retrieval": {
                "mode": "harness_only",
                "workflow_contract_schema": "2",
                "source": "neo4j-legacy-graph-rag",
                "eligibility": "measured-or-structural-v1",
                "continuation": "retained_exact_snapshot_only",
                "managed_source": "unsupported",
            },
            "distinct_principals_select_distinct_db_logins": False,
            "administration": (
                "Explicit administration uses the same DB login; administration may remain operator-owned."
            ),
        },
        "blockers": _blockers(selection, rows, databases),
        "limitations": [
            "Offline public inventory only; no access, capability, credential or authorization checks performed.",
            "Not a durable lifecycle registry, execution grant or live readiness receipt.",
            "The digest binds public selections only, not secret contents or credential generation.",
            (
                "Changed selections change the digest; same digest cannot detect key rotation, revocation or service"
                " drift."
            ),
            (
                "Revalidate affected bindings before any later authorized release; there are no stored checks to reuse"
                " here."
            ),
            (
                "Selections are public caller-supplied labels, not verified secret-free contents; never paste secrets"
                " into labels."
            ),
            (
                "This bounded checklist assumes generation, visual assessment, repair and prior reads; it is not"
                " contract admission."
            ),
        ],
    }


def setup_readiness_from_config(config):
    """Project validated public configuration without opening its credential source."""
    value = config.value
    roles = {}
    for role, binding in value.get("role_bindings", {}).items():
        credential = dict(alias=binding["credential_alias"], source="private_file", source_role=SOURCE_ROLES[role])
        if role == "prior_read":
            roles[role] = dict(
                provider="neo4j",
                endpoint=binding["endpoint"],
                database=binding["database"],
                authentication=binding["authentication"],
                tls="none",
                credential=credential,
            )
        else:
            settings = binding["profile"]["settings"]
            provider = next(name for name, endpoint in FIXED_ENDPOINTS.items() if endpoint == settings["endpoint"])
            roles[role] = dict(
                provider=provider,
                model=settings["model"],
                endpoint=settings["endpoint"],
                inference_profile=settings["inference_policy"],
                credential=credential,
            )
    roles["operational_db"] = dict(
        provider="neo4j",
        endpoint=value["bolt_uri"],
        database=config.binding.database,
        authentication="basic",
        tls="none",
        credential=dict(alias="databases.operational", source="private_file", source_role="databases.operational"),
    )
    report = setup_readiness(json.dumps(dict(schema_version=1, outcome="scene-only", roles=roles)).encode())
    report["installed_boundary"]["mode"] = value["mode"]
    report["configuration_sha256"] = config.digest
    return report
