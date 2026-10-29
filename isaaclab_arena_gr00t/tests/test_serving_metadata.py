# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Offline metadata producer/codec tests; never load a model or bind a socket."""

import numpy as np

import pytest
from gr00t.policy.server_client import MsgSerializer, PolicyServer

from isaaclab_arena.agentic_environment_generation.policy_contract import canonical_metadata_digest
from isaaclab_arena.tests.test_policy_contract import droid_modalities, server_info
from isaaclab_arena_gr00t.policy import serving_metadata


def serving():
    return serving_metadata


class N16Socket:
    def __init__(self):
        self.options, self.closed, self.sent, self.payload = {}, False, [], b"\x80"

    def setsockopt(self, key, value):
        self.options[key] = value

    def close(self, linger=0):
        assert linger == 0
        self.closed = True

    def connect(self, address):
        self.address = address

    def getsockopt_string(self, key):
        return "inert-test-peer"

    def send(self, data):
        self.sent.append(data)

    def recv(self):
        if isinstance(self.payload, Exception):
            raise self.payload
        return self.payload


class N16Context:
    def __init__(self):
        self.sockets, self.terminated = [], False

    def socket(self, kind):
        sock = N16Socket()
        self.sockets.append(sock)
        return sock

    def term(self):
        assert all(sock.closed for sock in self.sockets)
        self.terminated = True


def n16_client_init(self, host="localhost", port=5555, timeout_ms=15000, api_token=None, strict=False):
    # Exact N1.6 owned attributes; no _closed/close/context manager/recovery support.
    self.context = N16Context()
    self.strict = strict  # BasePolicy.__init__(strict=strict) in the real constructor.
    self.host, self.port, self.timeout_ms, self.api_token = host, port, timeout_ms, api_token
    self._init_socket()


def n16_call_endpoint(self, endpoint, data=None, requires_input=True):
    request = {"endpoint": endpoint}
    if requires_input:
        request["data"] = data
    self.socket.send(MsgSerializer.to_bytes(request))
    return MsgSerializer.from_bytes(self.socket.recv())


def test_n16_client_owned_close_and_timeout_recovery(monkeypatch):
    import zmq

    s = serving()
    monkeypatch.setattr(s.PolicyClient, "__init__", n16_client_init)
    monkeypatch.setattr(s.PolicyClient, "call_endpoint", n16_call_endpoint)
    monkeypatch.setattr(s.PolicyClient, "close", lambda self: pytest.fail("N1.6 has no close"), raising=False)
    monkeypatch.setattr(s, "verify_native_connection", lambda *args: None)
    client = s.VerifiedPolicyClient(expected_server_info=server_info())
    old = client.socket
    old.payload = zmq.Again()
    # The receive proxy delegates reads, so assign on the underlying inert socket.
    client.context.sockets[-1].payload = zmq.Again()
    with pytest.raises(zmq.Again):
        client.call_endpoint("ping", requires_input=False)
    assert old.closed
    assert client.socket is not old
    client.close()
    client.close()
    assert client.context.terminated


@pytest.mark.parametrize("side", ["client", "server"])
@pytest.mark.parametrize(
    "wire",
    [
        "legacy",
        "current",
        "legacy_bytes",
        "legacy_mixed_marker",
        "legacy_mixed_payload",
        "legacy_duplicate_marker",
        "legacy_duplicate_payload",
    ],
)
def test_native_receive_preflights_before_poisoned_decoder(monkeypatch, side, wire):
    import msgpack

    from isaaclab_arena.tests.test_policy_contract import npy_wire_header

    s = serving()
    value: dict[str | bytes, object] = {"__ndarray_class__": True, "as_npy": npy_wire_header()}
    if wire == "current":
        value = {b"nd": True, b"type": "<f8", b"kind": b"", b"shape": [2**50], b"data": b""}
    elif wire == "legacy_bytes":
        value = {key.encode() if isinstance(key, str) else key: item for key, item in value.items()}
    elif wire == "legacy_mixed_marker":
        value[b"__ndarray_class__"] = value.pop("__ndarray_class__")
    elif wire == "legacy_mixed_payload":
        value[b"as_npy"] = value.pop("as_npy")
    elif wire == "legacy_duplicate_marker":
        value[b"__ndarray_class__"] = True
    elif wire == "legacy_duplicate_payload":
        value[b"as_npy"] = value["as_npy"]
    malicious = msgpack.packb(value)
    decoder_calls = []

    def poisoned(raw):
        decoder_calls.append(raw)
        raise AssertionError("Native allocation decoder reached")

    monkeypatch.setattr(MsgSerializer, "from_bytes", poisoned)
    if side == "client":
        monkeypatch.setattr(s.PolicyClient, "__init__", n16_client_init)
        monkeypatch.setattr(s.PolicyClient, "call_endpoint", n16_call_endpoint)
        monkeypatch.setattr(s, "verify_native_connection", lambda *args: None)
        client = s.VerifiedPolicyClient(expected_server_info=server_info())
        client.context.sockets[-1].payload = malicious
        try:
            with pytest.raises(ValueError):
                client.call_endpoint("ping", requires_input=False)
        finally:
            client.close()
    else:

        def init(self, policy, host="*", port=5555, api_token=None):
            self.policy, self.running, self.api_token, self._endpoints = policy, True, api_token, {}
            self.context = N16Context()
            self.socket = self.context.socket(None)

        monkeypatch.setattr(PolicyServer, "__init__", init)
        monkeypatch.setattr(PolicyServer, "close", lambda self: pytest.fail("N1.6 has no close"), raising=False)
        with s._policy_server_type()(object()) as server:
            raw_socket = server.context.sockets[-1]
            raw_socket.payload = malicious
            send = raw_socket.send

            def stop(data):
                send(data)
                server.running = False

            raw_socket.send = stop
            server.run()  # Existing native dispatch loop, not a substitute engine.
        assert server.context.terminated
        assert len(raw_socket.sent) == 1
    assert decoder_calls == []


def test_preflight_accepts_actual_native_codec_without_weight_loading():
    from isaaclab_arena.agentic_environment_generation.policy_contract import safe_decode_native_message

    probe = serving().make_codec_probe()
    raw = MsgSerializer.to_bytes(probe)
    decoded = safe_decode_native_message(raw, MsgSerializer.from_bytes, max_bytes=4096, max_array_bytes=4096)
    serving().validate_codec_probe(decoded)
    for key in ("numeric", "image"):
        assert decoded[key].tobytes() == probe[key].tobytes()


def guarded_peer():
    """Use native dispatch and registered fake effects, without binding or loading."""
    effects = []

    class LoadedPolicy:
        model, processor = object(), object()

        def get_modality_config(self):
            return droid_modalities()

        def get_action(self, observation, options=None):
            effects.append(("get_action", observation, options))
            return [{"action": observation["state"]}, {}]

        def reset(self, options=None):
            effects.append(("reset", options))
            return {"reset": True}

    policy = LoadedPolicy()
    server = PolicyServer.__new__(PolicyServer)
    server.policy, server._endpoints, server.api_token = policy, {}, None
    server.socket = N16Socket()
    server.register_endpoint("ping", server._handle_ping, requires_input=False)
    server.register_endpoint("get_modality_config", policy.get_modality_config, requires_input=False)
    server.register_endpoint("get_action", policy.get_action)
    server.register_endpoint("reset", policy.reset)
    info = server_info()
    info["serializer_sha256"] = serving().native_serializer_sha256()
    info["modalities_sha256"] = canonical_metadata_digest(droid_modalities())
    serving().register_metadata_endpoints(server, policy, info)
    return server, info, effects


def dispatch_once(server, request):
    """Exercise the actual native dispatch loop over one inert serialized request."""
    server.socket.payload = MsgSerializer.to_bytes(request)
    server.running = True

    def reply(data):
        server.socket.sent.append(data)
        server.running = False

    server.socket.send = reply
    server.run()
    return server.socket.sent[-1]


@pytest.mark.parametrize("endpoint", ["get_action", "reset"])
@pytest.mark.parametrize("replacement", [False, True])
def test_guarded_client_checks_receiving_instance_before_effect(monkeypatch, endpoint, replacement):
    import zmq

    s = serving()
    original, expected, original_effects = guarded_peer()
    other, other_info, other_effects = guarded_peer()
    other_info["instance_id"] = "f" * 32
    s.register_metadata_endpoints(other, other.policy, other_info)
    current = original
    armed = False
    wire = []

    def init(self, **kwargs):
        n16_client_init(self, **kwargs)
        raw = self.context.sockets[-1]

        def receive():
            nonlocal current
            assert self._transport_lock._is_owned()
            request = MsgSerializer.from_bytes(raw.sent[-1])
            wire.append((request, raw.options[zmq.RCVTIMEO], raw.options[zmq.SNDTIMEO]))
            response = dispatch_once(current, request)
            if armed and replacement and request["endpoint"] == "get_server_info":
                current = other  # Replacement AFTER successful metadata, BEFORE effect request.
            return response

        raw.recv = receive

    monkeypatch.setattr(s.PolicyClient, "__init__", init)
    pin = expected.copy()
    observation = {"state": np.array([[1.0, 2.0]], dtype=np.float32)}
    options = {"test": "original options"}
    with s.VerifiedPolicyClient(expected_server_info=pin, timeout_ms=23000, metadata_timeout_ms=1100) as client:
        pin["instance_id"] = "e" * 32  # Caller mutation must never repin the client.
        wire.clear()
        armed = True
        error = None
        try:
            result = client._get_action(observation, options) if endpoint == "get_action" else client.reset(options)
        except (ValueError, RuntimeError) as exc:
            error = exc
        assert other_effects == [], "Endpoint replacement must not execute even one unapproved effect"
        assert len(original_effects) == (0 if replacement else 1)
        if replacement:
            assert error is not None
        else:
            assert error is None
            if endpoint == "get_action":
                np.testing.assert_array_equal(result[0]["action"], observation["state"])
            else:
                assert result == {"reset": True}
        expected_names = ["get_server_info", "verified_call"]
        if endpoint == "get_action" and not replacement:
            expected_names.append("get_server_info")
        assert [request["endpoint"] for request, _, _ in wire] == expected_names
        request, recv, send = wire[1]
        assert set(request) == {"endpoint", "data"}
        assert set(request["data"]) == {"expected_server_info", "endpoint", "data"}
        assert request["data"]["expected_server_info"] == expected
        assert client._expected_server_info == expected
        assert request["data"]["endpoint"] == endpoint
        body = request["data"]["data"]
        assert body["options"] == options
        assert set(body) == ({"observation", "options"} if endpoint == "get_action" else {"options"})
        if endpoint == "get_action":
            np.testing.assert_array_equal(body["observation"]["state"], observation["state"])
        assert recv == send == (23000 if endpoint == "get_action" else 1100)
        assert all(recv == send == 1100 for request, recv, send in wire if request["endpoint"] == "get_server_info")


@pytest.mark.parametrize("endpoint", ["get_action", "reset"])
@pytest.mark.parametrize(
    "change",
    [
        "extra-envelope",
        "missing-pin",
        "extra-pin",
        "missing-instance",
        "instance",
        "checkpoint",
        "config",
        "serializer",
        "modalities",
        "schema",
        "endpoint-kill",
        "endpoint-metadata",
        "endpoint-recursive",
        "endpoint-list",
        "body-null",
        "body-list",
        "body-extra",
        "body-missing-options",
        "body-options-type",
        "body-cross-endpoint",
        "body-observation-type",
        "bound-policy",
        "bound-model",
        "bound-processor",
        "bound-modalities",
        "bound-serializer",
    ],
)
def test_guarded_server_rejects_invalid_request_before_effect(monkeypatch, endpoint, change):
    server, info, effects = guarded_peer()
    body: dict = {"options": None}
    if endpoint == "get_action":
        body["observation"] = {"state": np.zeros((1, 2), dtype=np.float32)}
    envelope = {"expected_server_info": info.copy(), "endpoint": endpoint, "data": body}
    pin = envelope["expected_server_info"]
    if change == "extra-envelope":
        envelope["unknown"] = True
    elif change == "missing-pin":
        del envelope["expected_server_info"]
    elif change == "extra-pin":
        pin["unknown"] = True
    elif change == "missing-instance":
        del pin["instance_id"]
    elif change == "instance":
        pin["instance_id"] = "f" * 32
    elif change in {"checkpoint", "config", "serializer", "modalities"}:
        pin[change + "_sha256"] = "f" * 64
    elif change == "schema":
        pin["schema_version"] = True
    elif change.startswith("endpoint-"):
        envelope["endpoint"] = {
            "endpoint-kill": "kill",
            "endpoint-metadata": "get_server_info",
            "endpoint-recursive": "verified_call",
            "endpoint-list": ["get_action"],
        }[change]
    elif change == "body-null":
        envelope["data"] = None
    elif change == "body-list":
        envelope["data"] = []
    elif change == "body-extra":
        body["unknown"] = True
    elif change == "body-missing-options":
        del body["options"]
    elif change == "body-options-type":
        body["options"] = "not a mapping"
    elif change == "body-cross-endpoint":
        if endpoint == "get_action":
            del body["observation"]
        else:
            body["observation"] = {}
    elif change == "body-observation-type":
        body["observation"] = []
    elif change in {"bound-policy", "bound-model", "bound-processor"}:
        if change == "bound-policy":
            server.policy = object()
        else:
            setattr(server.policy, change.removeprefix("bound-"), object())
    elif change == "bound-modalities":
        server.policy.get_modality_config = lambda: {}
    elif change == "bound-serializer":
        monkeypatch.setattr(serving(), "native_serializer_sha256", lambda: "f" * 64)
    response = MsgSerializer.from_bytes(dispatch_once(server, {"endpoint": "verified_call", "data": envelope}))
    assert effects == [], "All request and bound-policy validation must precede any effect"
    assert "error" in response


@pytest.mark.parametrize("endpoint", ["get_action", "reset"])
def test_guarded_peer_without_endpoint_fails_closed_and_legacy_still_works(monkeypatch, endpoint):
    s = serving()
    server, info, effects = guarded_peer()

    def init(self, **kwargs):
        n16_client_init(self, **kwargs)
        raw = self.context.sockets[-1]
        raw.recv = lambda: dispatch_once(server, MsgSerializer.from_bytes(raw.sent[-1]))

    monkeypatch.setattr(s.PolicyClient, "__init__", init)
    data: dict = {"options": None}
    if endpoint == "get_action":
        data["observation"] = {"state": np.zeros((1, 2), dtype=np.float32)}
    with s.VerifiedPolicyClient(expected_server_info=info) as client:
        del server._endpoints["verified_call"]  # Older unreleased peer, not a fallback grant.
        raw = client.context.sockets[-1]
        raw.sent.clear()
        with pytest.raises(RuntimeError, match="Unknown endpoint"):
            client.call_endpoint(endpoint, data)
        assert effects == []
        assert len(raw.sent) == 1  # No retry or legacy fallback.
        assert MsgSerializer.from_bytes(raw.sent[0])["endpoint"] == "verified_call"
    response = MsgSerializer.from_bytes(dispatch_once(server, {"endpoint": endpoint, "data": data}))
    assert "error" not in response
    assert len(effects) == 1 and effects[0][0] == endpoint


@pytest.mark.parametrize("endpoint", ["get_action", "reset"])
def test_guarded_client_timeout_never_retries_effect(monkeypatch, endpoint):
    import zmq

    s = serving()
    monkeypatch.setattr(s.PolicyClient, "__init__", n16_client_init)
    monkeypatch.setattr(s, "verify_native_connection", lambda *args: None)
    with s.VerifiedPolicyClient(expected_server_info=server_info()) as client:
        raw = client.context.sockets[-1]
        raw.payload = zmq.Again()
        with pytest.raises(zmq.Again):
            client.call_endpoint(endpoint, {"options": None})
        assert len(raw.sent) == 1 and raw.closed
        assert MsgSerializer.from_bytes(raw.sent[0])["endpoint"] == "verified_call"
        assert client.context.sockets[-1].sent == []
        assert client._verified_socket is None


def test_codec_echo_uses_native_arrays_and_binds_same_policy():
    s = serving()
    policy = type("LoadedPolicy", (), {"get_modality_config": lambda self: droid_modalities()})()
    policy.model, policy.processor = object(), object()
    server = PolicyServer.__new__(PolicyServer)
    server.policy, server._endpoints = policy, {}
    info = server_info()
    info["modalities_sha256"] = canonical_metadata_digest(droid_modalities())
    info["serializer_sha256"] = s.native_serializer_sha256()
    s.register_metadata_endpoints(server, policy, info)
    detached = server._endpoints["get_server_info"].handler()
    assert detached == info and detached is not info
    probe = s.make_codec_probe()
    request = MsgSerializer.from_bytes(MsgSerializer.to_bytes({"probe": probe}))
    result = server._endpoints["codec_echo"].handler(**request)
    decoded = MsgSerializer.from_bytes(MsgSerializer.to_bytes(result))
    s.validate_codec_echo(decoded, probe, info)
    assert decoded["probe"]["image"].dtype == np.uint8
    server.policy = object()
    with pytest.raises(ValueError):
        server._endpoints["get_server_info"].handler()


@pytest.mark.parametrize("change", ["dtype", "shape", "bytes", "extra", "identity"])
def test_codec_echo_rejects_changes(change):
    s = serving()
    probe = s.make_codec_probe()
    info = server_info()
    response = {
        "server_info": info.copy(),
        "probe": {key: value.copy() if isinstance(value, np.ndarray) else value for key, value in probe.items()},
    }
    if change == "dtype":
        response["probe"]["numeric"] = probe["numeric"].astype(np.float64)
    elif change == "shape":
        response["probe"]["image"] = probe["image"].reshape(-1)
    elif change == "bytes":
        response["probe"]["image"].flat[0] ^= 1
    elif change == "extra":
        response["extra"] = "forbidden"
    else:
        response["server_info"]["instance_id"] = "f" * 32
    with pytest.raises(ValueError):
        s.validate_codec_echo(response, probe, info)


def test_codec_echo_rejects_unbounded_probe_without_inference():
    s = serving()
    probe = s.make_codec_probe()
    probe["image"] = np.zeros((100, 100, 3), dtype=np.uint8)
    with pytest.raises(ValueError):
        s.validate_codec_probe(probe)


def test_fingerprint_binds_bytes_and_config_without_reading_secrets(tmp_path):
    s = serving()
    (tmp_path / "model.safetensors").write_bytes(b"synthetic test artifact, not real weights")
    (tmp_path / "config.json").write_text('{"model_type":"test"}')
    first = s.fingerprint_artifacts(tmp_path)
    (tmp_path / "config.json").write_text('{"model_type":"changed"}')
    changed = s.fingerprint_artifacts(tmp_path)
    assert first["checkpoint_sha256"] == changed["checkpoint_sha256"]
    assert first["config_sha256"] != changed["config_sha256"]
    (tmp_path / "model.safetensors").write_bytes(b"changed synthetic artifact")
    assert s.fingerprint_artifacts(tmp_path)["checkpoint_sha256"] != changed["checkpoint_sha256"]
    (tmp_path / ".env").write_text("DO_NOT_READ")
    with pytest.raises(ValueError):
        s.fingerprint_artifacts(tmp_path)


def test_n16_processor_layout_hashes_normalization_and_embodiment(tmp_path):
    import json

    (tmp_path / "model.safetensors").write_bytes(b"synthetic, never loaded")
    (tmp_path / "config.json").write_text("{}")
    processor = tmp_path
    # N1.6 Gr00tPolicy loads AutoProcessor.from_pretrained(model_dir), not a subfolder.
    # processing_gr00t_n1d6.py:448-512 saves/reads these exact root data files.
    files = {
        "processor_config.json": {"processor_class": "Gr00tN1d6Processor", "processor_kwargs": {}},
        "statistics.json": {"oxe_droid": {"state": {}}},
        "embodiment_id.json": {"oxe_droid": 17},
    }
    for name, value in files.items():
        (processor / name).write_text(json.dumps(value))
    previous = serving().fingerprint_artifacts(tmp_path)
    for name in files:
        (processor / name).write_text(json.dumps({"changed": name}))
        current = serving().fingerprint_artifacts(tmp_path)
        assert current["config_sha256"] != previous["config_sha256"]
        assert current["checkpoint_sha256"] == previous["checkpoint_sha256"]
        previous = current


def test_fingerprint_rejects_symlinks(tmp_path):
    s = serving()
    (tmp_path / "config.json").write_text("{}")
    (tmp_path / "model.safetensors").symlink_to(tmp_path / "config.json")
    with pytest.raises(ValueError):
        s.fingerprint_artifacts(tmp_path)


def test_offline_loader_compares_approval_before_load_and_registers_after(monkeypatch, tmp_path):
    s = serving()
    (tmp_path / "model.safetensors").write_bytes(b"synthetic")
    (tmp_path / "config.json").write_text("{}")
    approved = s.fingerprint_artifacts(tmp_path)
    calls = []
    policy = type("LoadedPolicy", (), {"get_modality_config": lambda self: droid_modalities()})()
    policy.model, policy.processor = object(), object()

    def load(path, device):
        import os

        assert os.environ["HF_HUB_OFFLINE"] == "1"
        assert os.environ["TRANSFORMERS_OFFLINE"] == "1"
        calls.append((path, device))
        return policy

    monkeypatch.setattr(s, "_load_policy", load)

    class Server:
        def __init__(self, loaded, **kwargs):
            assert loaded is policy
            self.policy, self._endpoints = loaded, {}

        register_endpoint = PolicyServer.register_endpoint

    monkeypatch.setattr(s, "_policy_server_type", lambda: Server)
    with pytest.raises(ValueError):
        s.create_server(tmp_path, checkpoint_sha256="f" * 64, config_sha256=approved["config_sha256"])
    assert calls == []
    server = s.create_server(tmp_path, **approved)
    assert len(calls) == 1
    info = server._endpoints["get_server_info"].handler()
    assert info["checkpoint_sha256"] == approved["checkpoint_sha256"]
    assert info["config_sha256"] == approved["config_sha256"]
    assert info["serializer_sha256"] == s.native_serializer_sha256()


def test_offline_loader_rejects_changed_artifacts_during_load(monkeypatch, tmp_path):
    s = serving()
    (tmp_path / "model.safetensors").write_bytes(b"synthetic")
    (tmp_path / "config.json").write_text("{}")
    approved = s.fingerprint_artifacts(tmp_path)

    def load(path, device):
        (tmp_path / "config.json").write_text('{"changed":true}')
        return object()

    monkeypatch.setattr(s, "_load_policy", load)
    with pytest.raises(ValueError):
        s.create_server(tmp_path, **approved)


class CodecPeer:
    """Wire boundary peer runs real MsgSerializer on requests and responses."""

    def __init__(self):
        self.info = server_info()
        self.info["serializer_sha256"] = serving().native_serializer_sha256()
        self.info["modalities_sha256"] = canonical_metadata_digest(droid_modalities())
        self.calls = []
        self.change = None

    def call_endpoint(self, endpoint, data=None, requires_input=True):
        self.calls.append(endpoint)
        if endpoint == "ping":
            result = {"status": "ok", "message": "Server is running"}
            if self.change == "ping":
                result = {"status": "error"}
        elif endpoint == "get_modality_config":
            result = droid_modalities()
        elif endpoint == "get_server_info":
            result = self.info.copy()
        elif endpoint == "codec_echo":
            data = MsgSerializer.from_bytes(MsgSerializer.to_bytes(data))
            result = {"server_info": self.info.copy(), "probe": data["probe"]}
            if self.change == "codec":
                result["probe"]["image"] = result["probe"]["image"].copy()
                result["probe"]["image"].flat[0] ^= 1
            if self.change == "restart":
                self.info["instance_id"] = "f" * 32
        else:
            raise AssertionError("Unexpected inference/effect endpoint")
        return MsgSerializer.from_bytes(MsgSerializer.to_bytes(result))


def test_native_connection_verifies_actual_codec_and_same_instance():
    s = serving()
    peer = CodecPeer()
    assert s.verify_native_connection(peer, peer.info) == peer.info
    assert peer.calls == ["ping", "get_server_info", "get_modality_config", "codec_echo", "get_server_info"]


@pytest.mark.parametrize("change", ["ping", "codec", "restart", "serializer", "model"])
def test_native_connection_rejects_unverified_peer(change):
    s = serving()
    peer = CodecPeer()
    expected = peer.info.copy()
    if change == "serializer":
        peer.info["serializer_sha256"] = expected["serializer_sha256"] = "f" * 64
    elif change == "model":
        peer.info["checkpoint_sha256"] = "f" * 64
    else:
        peer.change = change
    with pytest.raises(ValueError):
        s.verify_native_connection(peer, expected)


def test_verified_client_reconnect_closes_old_socket_and_sets_bounds():
    s = serving()
    import zmq

    class Socket:
        def __init__(self):
            self.options, self.closed = {}, False

        def setsockopt(self, key, value):
            self.options[key] = value

        def close(self, linger):
            assert linger == 0
            self.closed = True

        def connect(self, address):
            self.address = address

    class Context:
        def socket(self, kind):
            assert kind == zmq.REQ
            return Socket()

    client = s.VerifiedPolicyClient.__new__(s.VerifiedPolicyClient)
    client.context, client.socket = Context(), Socket()
    old = client.socket
    client.host, client.port, client.timeout_ms = "localhost", 5555, 1000
    client._init_socket()
    assert old.closed
    assert client.socket.options[zmq.MAXMSGSIZE] == s.NATIVE_MAX_MESSAGE_BYTES
    assert client.socket.options[zmq.LINGER] == 0
    assert client.socket.options[zmq.RCVTIMEO] == 1000
    client._closed = True


def test_verified_native_action_and_reset_recheck_under_one_transport_lock():
    import threading

    s = serving()
    peer = CodecPeer()
    client = s.VerifiedPolicyClient.__new__(s.VerifiedPolicyClient)
    client._expected_server_info = peer.info.copy()
    client._transport_lock = threading.RLock()
    client._closed = True
    seen = []

    def endpoint(name, data=None, requires_input=True):
        assert client._transport_lock._is_owned(), "Verification and effects must share the same lock"
        if name in ("get_action", "reset"):
            seen.append(name)
            peer.info["instance_id"] = "f" * 32
            return [{"action": np.zeros((1, 1))}, {}]
        return peer.call_endpoint(name, data, requires_input)

    client.call_endpoint = endpoint
    with pytest.raises(ValueError, match="identity"):
        client._get_action({})
    assert seen == ["get_action"]
    with pytest.raises(ValueError, match="identity"):
        client.reset()
    assert seen == ["get_action"]


def test_verified_rpc_counts_and_separate_deadlines(monkeypatch):
    import zmq

    s = serving()
    peer = CodecPeer()
    timeouts = []
    monkeypatch.setattr(s.PolicyClient, "__init__", n16_client_init)

    def endpoint(self, name, data=None, requires_input=True):
        timeouts.append((name, self.socket.options[zmq.RCVTIMEO], self.socket.options[zmq.SNDTIMEO]))
        if name == "verified_call":
            assert requires_input is True
            assert type(data) is dict
            assert data["expected_server_info"] == peer.info
            assert data["expected_server_info"] is not self._expected_server_info
            assert data["endpoint"] == "get_action"
            assert data["data"] == {"observation": {}, "options": None}
            peer.calls.append(name)
            return [{}, {}]
        return peer.call_endpoint(name, data, requires_input)

    monkeypatch.setattr(s.PolicyClient, "call_endpoint", endpoint)
    with s.VerifiedPolicyClient(expected_server_info=peer.info) as client:
        assert client.timeout_ms == 15000
        assert peer.calls == ["ping", "get_server_info", "get_modality_config", "codec_echo", "get_server_info"]
        peer.calls.clear()
        client._get_action({})
        assert peer.calls == ["get_server_info", "verified_call", "get_server_info"]
        assert all(recv == send == (15000 if name == "verified_call" else 3000) for name, recv, send in timeouts)
        peer.calls.clear()
        client.verify_identity()
        assert peer.calls == ["get_server_info"]
        client._init_socket()
        peer.calls.clear()
        client.verify_identity()
        assert peer.calls == ["ping", "get_server_info", "get_modality_config", "codec_echo", "get_server_info"]
        peer.info["instance_id"] = "f" * 32
        with pytest.raises(ValueError):
            client._get_action({})
        assert peer.calls[-1] == "get_server_info"
    peer = CodecPeer()
    with s.VerifiedPolicyClient(expected_server_info=peer.info, timeout_ms=25000, metadata_timeout_ms=1200) as client:
        timeouts.clear()
        client._get_action({})
        assert timeouts == [
            ("get_server_info", 1200, 1200),
            ("verified_call", 25000, 25000),
            ("get_server_info", 1200, 1200),
        ]


def test_cli_help_and_fingerprint_mode_never_load_or_bind(monkeypatch, capsys, tmp_path):
    s = serving()
    with pytest.raises(SystemExit) as result:
        s.main(["--help"])
    assert result.value.code == 0
    help_text = capsys.readouterr().out
    assert "--checkpoint-sha256" in help_text
    assert "does not cover runtime Eagle" in help_text
    (tmp_path / "model.safetensors").write_bytes(b"synthetic fixture")
    (tmp_path / "config.json").write_text("{}")

    def forbidden(*args, **kwargs):
        raise AssertionError("Fingerprint mode must not load or bind")

    monkeypatch.setattr(s, "_load_policy", forbidden)
    monkeypatch.setattr(s, "_policy_server_type", forbidden)
    s.main(["--model-path", str(tmp_path), "--fingerprint-only"])
    import json

    assert json.loads(capsys.readouterr().out) == s.fingerprint_artifacts(tmp_path)


def test_serving_refuses_no_weight_test_mode_before_artifact_access(monkeypatch, tmp_path):
    s = serving()
    monkeypatch.setenv("GROOT_SKIP_HF_MODEL_WEIGHTS", "1")
    with pytest.raises(ValueError, match="test-only"):
        s.create_server(tmp_path / "not-present", checkpoint_sha256="b" * 64, config_sha256="c" * 64)


def test_loader_requires_offline_hub_state_before_importing_model(monkeypatch, tmp_path):
    import builtins

    from huggingface_hub import constants

    original_import = builtins.__import__

    def guarded_import(name, *args, **kwargs):
        if name == "gr00t.policy.gr00t_policy":
            raise AssertionError("Model import before offline preflight")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", guarded_import)
    monkeypatch.setattr(constants, "HF_HUB_OFFLINE", False)
    with pytest.raises(ValueError, match="fresh offline"):
        serving()._load_policy(tmp_path, "cpu")
