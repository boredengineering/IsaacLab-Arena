# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Synthetic bounded metadata transport units; no server or model is contacted."""

import msgpack
import pytest

from isaaclab_arena_examples.agentic_environment_generation.web_api import policy_readiness as policy


def metadata_fixture():
    import hashlib
    import json

    modalities = {
        "video": {
            "delta_indices": [0],
            "modality_keys": ["exterior_image_1_left", "wrist_image_left"],
        },
        "state": {
            "delta_indices": [0],
            "modality_keys": ["joint_position", "gripper_position"],
        },
        "action": {
            "delta_indices": list(range(32)),
            "modality_keys": ["joint_position", "gripper_position"],
        },
        "language": {
            "delta_indices": [0],
            "modality_keys": ["annotation.language.language_instruction"],
        },
    }
    digest = hashlib.sha256(
        json.dumps(
            modalities,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()
    info = {
        "schema_version": 1,
        "instance_id": "c" * 32,
        "checkpoint_id": "nvidia/GR00T-N1.6-DROID",
        "checkpoint_sha256": "a" * 64,
        "config_sha256": "b" * 64,
        "embodiment": "OXE_DROID",
        "serializer_sha256": "d" * 64,
        "modalities_sha256": digest,
    }
    return modalities, info


@pytest.mark.parametrize(
    "fault",
    [
        None,
        "ping",
        "modalities",
        "checkpoint",
        "instance",
        "no_expectation",
        "no_metadata",
        "cleanup",
    ],
)
def test_protocol_model_and_transport_are_distinct_and_same_instance(monkeypatch, fault):
    probe = getattr(policy, "probe_gr00t", None)
    assert callable(probe), "Strict protocol and pinned model verification is required"
    modalities, info = metadata_fixture()
    calls = []

    class Peer:
        def __init__(self, *, port):
            assert port == 5555

        def __enter__(self):
            return self

        def __exit__(self, *_):
            if fault == "cleanup":
                raise RuntimeError("private cleanup diagnostic")

        def call(self, endpoint):
            calls.append(endpoint)
            if endpoint == "ping":
                return {"status": "ok"} if fault == "ping" else {"status": "ok", "message": "Server is running"}
            if endpoint == "get_modality_config":
                if fault == "modalities":
                    return {
                        **modalities,
                        "action": {
                            **modalities["action"],
                            "delta_indices": list(range(16)),
                        },
                    }
                return modalities
            if fault == "no_metadata":
                return {"error": "synthetic-secret"}
            if fault == "instance" and calls.count("get_server_info") == 2:
                return {**info, "instance_id": "f" * 32}
            return {**info, "checkpoint_sha256": "e" * 64} if fault == "checkpoint" else info

    monkeypatch.setattr(policy, "MetadataPeer", Peer)
    # This test intentionally proves metadata cannot certify native codec transport.
    monkeypatch.setattr(policy, "verify_native_transport", lambda _info, **_kwargs: False, raising=False)
    expected = None if fault == "no_expectation" else {"checkpoint_sha256": "a" * 64, "config_sha256": "b" * 64}
    result = probe(expected)
    assert set(result) == {
        "policy_protocol",
        "policy_model",
        "policy_transport",
        "evidence",
        "server_info",
    }
    assert result["policy_transport"] == {
        "status": "not_checked",
        "code": "policy_transport_unverified",
    }
    assert result["policy_model"]["status"] == (
        "passed"
        if fault is None
        else (
            "not_checked"
            if fault == "no_expectation"
            else ("unavailable" if fault in ("ping", "no_metadata", "cleanup") else "mismatch")
        )
    )
    assert "synthetic-secret" not in str(result)
    if fault is None:
        assert result["server_info"] == info
        assert result["evidence"]["instance_id"] == info["instance_id"]
        assert result["evidence"]["inference"] == "not_run"
    else:
        assert result["server_info"] is None
    assert set(calls) <= {"ping", "get_modality_config", "get_server_info"}


def test_worker_policy_projection_rejects_conflicting_or_unbounded_evidence():
    validate = getattr(policy, "validate_probe_result", None)
    assert callable(validate), "Worker policy receipts require exact validation"
    value = {
        "policy_protocol": {
            "status": "unavailable",
            "code": "policy_protocol_unavailable",
        },
        "policy_model": {
            "status": "unavailable",
            "code": "policy_metadata_unavailable",
        },
        "policy_transport": {
            "status": "not_checked",
            "code": "policy_transport_unverified",
        },
        "evidence": None,
        "server_info": None,
    }
    assert validate(value) == value
    for key, bad in (
        ("policy_protocol", {"status": "passed", "code": "raw-secret"}),
        ("evidence", {"inference": "passed"}),
        ("server_info", metadata_fixture()[1]),
    ):
        with pytest.raises(ValueError):
            validate({**value, key: bad})


def test_native_codec_decoder_checks_small_wire_arrays_before_native_decode():
    decode = getattr(policy, "decode_codec_reply", None)
    assert callable(decode), "Native decoding requires a bounded array wire preflight"
    _, info = metadata_fixture()
    value = {
        "server_info": info,
        "probe": {
            "nonce": "a" * 32,
            "numeric": {
                b"nd": True,
                b"kind": b"",
                b"type": "<f4",
                b"shape": [1, 4],
                b"data": b"n" * 16,
            },
            "image": {
                b"nd": True,
                b"kind": b"",
                b"type": "|u1",
                b"shape": [1, 2, 3, 3],
                b"data": b"i" * 18,
            },
        },
    }
    calls = []
    payload = msgpack.packb(value)
    assert decode(payload, lambda data: calls.append(data) or "decoded") == "decoded"
    assert calls == [payload]
    for field, bad in (
        (b"type", "O"),
        (b"shape", [100000000]),
        (b"data", b"short"),
        (b"nd", 1),
    ):
        changed = {
            **value,
            "probe": {
                **value["probe"],
                "numeric": {**value["probe"]["numeric"], field: bad},
            },
        }
        with pytest.raises(ValueError):
            decode(
                msgpack.packb(changed),
                lambda _: pytest.fail("Unsafe native decoder reached"),
            )
    with pytest.raises(ValueError):
        decode(b"x" * 4097, lambda _: pytest.fail("Oversize native decoder reached"))


@pytest.mark.parametrize("port", [5555, 5559, 1, 65535])
def test_probe_requires_default_native_codec_verification_before_transport_pass(
    monkeypatch, port,
):
    modalities, info = metadata_fixture()
    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-capture")

    class Peer:
        def __init__(self, *, port):
            calls.append(("metadata", port))

        def __enter__(self):
            return self

        def __exit__(self, *_):
            pass

        def call(self, endpoint):
            return {
                "ping": {"status": "ok", "message": "Server is running"},
                "get_modality_config": modalities,
                "get_server_info": info,
            }[endpoint]

    calls = []
    monkeypatch.setattr(policy, "MetadataPeer", Peer)
    monkeypatch.setattr(
        policy,
        "verify_native_transport",
        lambda expected, **kwargs: calls.append((expected, kwargs)) or True,
        raising=False,
    )
    result = policy.probe_gr00t({"checkpoint_sha256": "a" * 64, "config_sha256": "b" * 64}, port=port)
    assert calls == [("metadata", port), (info, {"port": port})]
    assert result["policy_transport"] == {
        "status": "passed",
        "code": "policy_transport_verified",
    }


@pytest.mark.parametrize("port", [5555, 5559])
def test_native_codec_peer_calls_shared_verifier_with_fixed_bounded_transport(
    monkeypatch, port,
):
    verify = getattr(policy, "verify_native_transport", None)
    assert callable(verify), "Actual native helper integration is required"
    _, info = metadata_fixture()
    calls = []

    class Peer:
        def __init__(self, serializer, **kwargs):
            assert kwargs == {"port": port}
            assert serializer == "native-serializer-fixture"

        def __enter__(self):
            return self

        def __exit__(self, *_):
            calls.append("closed")

    def helper(client, expected):
        assert isinstance(client, Peer)
        assert expected == info
        calls.append("native-helper")
        return dict(info)

    monkeypatch.setattr(
        policy,
        "native_components",
        lambda: ("native-serializer-fixture", helper),
        raising=False,
    )
    monkeypatch.setattr(policy, "NativeCodecPeer", Peer, raising=False)
    assert verify(info, port=port) is True
    assert calls == ["native-helper", "closed"]


@pytest.mark.parametrize("port", [None, 5559, 1, 65535])
@pytest.mark.parametrize("native", [False, True])
def test_metadata_peer_only_allows_explicit_safe_rpc_and_closes_owned_context(monkeypatch, native, port):
    from types import SimpleNamespace

    import zmq

    peer = getattr(policy, "NativeCodecPeer" if native else "MetadataPeer", None)
    assert peer is not None, "A fixed-target bounded peer is required"
    events = []

    class Socket:
        def setsockopt(self, key, value):
            events.append(("option", key, value))

        def connect(self, target):
            events.append(("connect", target))

        def send(self, data):
            events.append(("send", msgpack.unpackb(data, raw=False)))

        def recv(self):
            return msgpack.packb({"status": "ok", "message": "Server is running"})

        def close(self, linger):
            events.append(("close", linger))

    sock = Socket()
    context = SimpleNamespace(socket=lambda kind: sock, term=lambda: events.append(("term",)))
    monkeypatch.setattr(zmq, "Context", lambda: context)
    monkeypatch.setenv("ARENA_WORKBENCH_GR00T_PORT", "invalid-after-capture")
    kwargs = {} if port is None else {"port": port}
    instance = peer(SimpleNamespace(to_bytes=msgpack.packb), **kwargs) if native else peer(**kwargs)
    with instance as rpc:
        call = (lambda endpoint: rpc.call_endpoint(endpoint, requires_input=False)) if native else rpc.call
        assert call("ping") == {"status": "ok", "message": "Server is running"}
        for endpoint in ("", "get_action", "reset", "kill", "codec_echo"):
            with pytest.raises(ValueError):
                call(endpoint)
    assert ("connect", f"tcp://127.0.0.1:{5555 if port is None else port}") in events
    assert ("option", zmq.MAXMSGSIZE, 64 * 1024) in events
    assert ("option", zmq.LINGER, 0) in events
    assert [event for event in events if event[0] == "send"] == [("send", {"endpoint": "ping"})]
    assert events[-2:] == [("close", 0), ("term",)]


def test_metadata_decoder_supports_bounded_modality_wrappers_without_json_ambiguity():
    raw = {
        "__ModalityConfig__": True,
        "as_json": b'{"delta_indices":[0],"modality_keys":["joint_position"]}',
    }
    parsed = policy.decode_metadata(msgpack.packb({"state": raw}))
    assert parsed["state"]["as_json"] == {
        "delta_indices": [0],
        "modality_keys": ["joint_position"],
    }
    for payload in ('{"delta_indices":[0],"delta_indices":[1]}', '{"value":NaN}'):
        with pytest.raises(ValueError):
            policy.decode_metadata(msgpack.packb({"state": {**raw, "as_json": payload}}))


@pytest.mark.parametrize("port", [None, True, False, 0, -1, 65536, 5559.0, "5559", [], {}])
def test_policy_endpoint_rejects_invalid_port_before_context(monkeypatch, port):
    import zmq

    monkeypatch.setattr(zmq, "Context", lambda: pytest.fail("Invalid endpoint reached socket context"))
    with pytest.raises(ValueError):
        with policy.MetadataPeer(port=port):
            pass
    with pytest.raises(ValueError):
        policy.probe_gr00t(None, port=port)


def test_metadata_decoder_is_plain_bounded_and_rejects_unsafe_or_ambiguous_maps():
    decode = getattr(policy, "decode_metadata", None)
    assert callable(decode), "A bounded metadata-only decoder is required"
    assert decode(msgpack.packb({"status": "ok"})) == {"status": "ok"}
    for value in (
        {b"nd": True, b"kind": b"O", b"data": b"never unpickle"},
        {"__ndarray_class__": True, "as_npy": b"never load"},
        msgpack.ExtType(1, b"never invoke"),
    ):
        with pytest.raises(ValueError):
            decode(msgpack.packb(value))
    with pytest.raises(ValueError):
        decode(b"\x82\xa1a\x01\xa1a\x02")
    with pytest.raises(ValueError):
        decode(b"x" * (64 * 1024 + 1))
    with pytest.raises(ValueError):
        decode(msgpack.packb({"nested": [[[[[[[[[[[[[[[[[1]]]]]]]]]]]]]]]]]}))
