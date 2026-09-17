# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Approved offline GR00T serving and native-codec verification, without inference probes.

Run with ``python -m isaaclab_arena_gr00t.policy.serving_metadata --help``.
Use a private, immutable, materialized local model directory (no symlinks).
Artifact hashes prove local provenance under a trusted server, not hardware attestation.
config_sha256 does not cover runtime Eagle processor/tokenizer/backbone configuration
or SDK code: it hashes model-directory data only. Independently pin/trust the installed
N1.6 runtime and its gr00t/model/modules/nvidia/Eagle-Block2A-2B-v2 dependencies.
The unreleased first-party v1 contract includes verified_call for pinned effects;
older peers without it fail closed, with no fallback to legacy effect endpoints.
"""

from __future__ import annotations

import argparse
import hashlib
import inspect
import json
import os
import re
import secrets
import stat
import threading
from contextlib import nullcontext, suppress
from pathlib import Path

from isaaclab_arena.agentic_environment_generation.policy_contract import (
    CHECKPOINT_ID,
    NATIVE_MAX_MESSAGE_BYTES,
    canonical_metadata_digest,
    preflight_native_message,
    validate_droid_modalities,
    validate_server_info,
)

# CLI startup must set offline mode before even native GR00T package imports.
# Importing this module as a client library must not alter the host process mode.
if __name__ == "__main__":
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"

from gr00t.policy.server_client import PolicyClient, PolicyServer  # noqa: E402  # isort: skip

CODEC_MAX_BYTES = 4096

_CONFIG_NAMES = {
    "config.json",
    "generation_config.json",
    "processor_config.json",
    "preprocessor_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "special_tokens_map.json",
    "added_tokens.json",
    "vocab.json",
    "merges.txt",
    "chat_template.json",
    "chat_template.jinja",
    "stats.json",
    # N1.6 processing_gr00t_n1d6.py:448-512 processor data, not executable code.
    "statistics.json",
    "embodiment_id.json",
    "model.safetensors.index.json",
}


def _file_digest(path):
    """Hash a regular, non-symlink file in chunks and reject concurrent mutation."""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode):
            raise ValueError("Artifact is not regular")
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb", closefd=False) as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        after = os.fstat(fd)
        if (before.st_ino, before.st_size, before.st_mtime_ns, before.st_ctime_ns) != (
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ):
            raise ValueError("Artifact changed while hashing")
        return {"size": before.st_size, "sha256": digest.hexdigest()}
    finally:
        os.close(fd)


def fingerprint_artifacts(model_path):
    """Hash model-directory bytes only, not the separate runtime Eagle configuration.

    Reject unknown files before reading any. N1.6's processor and backbone resolve
    Eagle configuration/tokenizer files relative to their installed SDK modules;
    this digest is not complete runtime/config verification.
    """
    root = Path(model_path).absolute()
    if not root.is_dir() or any(part.is_symlink() for part in (root, *root.parents)):
        raise ValueError("Model must be a materialized local directory")
    paths = []
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in dirs:
            child = Path(directory) / name
            if child.is_symlink() or child.relative_to(root).as_posix() != "processor":
                raise ValueError("Unapproved model directory")
        for name in files:
            path = Path(directory) / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                raise ValueError("Unapproved artifact type")
            is_weight = bool(re.fullmatch(r"model(?:-\d{5}-of-\d{5})?\.safetensors", name)) and path.parent == root
            if not is_weight and name not in _CONFIG_NAMES:
                raise ValueError("Unapproved model artifact")
            paths.append((relative, path, is_weight))
            if len(paths) > 256:
                raise ValueError("Artifact count limit")
    weights, configs = [], []
    for relative, path, is_weight in sorted(paths):
        record = {"path": relative, **_file_digest(path)}
        (weights if is_weight else configs).append(record)
    if not weights or not any(item["path"] == "config.json" for item in configs):
        raise ValueError("Missing model artifacts")
    return {
        "checkpoint_sha256": canonical_metadata_digest({"files": weights}),
        "config_sha256": canonical_metadata_digest({"files": configs}),
    }


def native_serializer_sha256():
    """Fingerprint the actual imported native serializer module's source bytes."""
    from gr00t.policy.server_client import MsgSerializer

    source = inspect.getsourcefile(MsgSerializer)
    if source is None:
        raise ValueError("Native serializer source unavailable")
    return _file_digest(Path(source))["sha256"]


def make_codec_probe():
    """Return a fresh bounded nonce and numeric/image arrays for the native codec."""
    import numpy as np

    return {
        "nonce": secrets.token_hex(16),
        "numeric": np.array([[0.0, -1.5, 2.25, 17.0]], dtype=np.float32),
        "image": np.arange(18, dtype=np.uint8).reshape(1, 2, 3, 3),
    }


def validate_codec_probe(probe):
    """Validate exact small arrays before echoing; never execute the model."""
    import numpy as np

    from gr00t.policy.server_client import MsgSerializer

    if type(probe) is not dict or set(probe) != {"nonce", "numeric", "image"}:
        raise ValueError("Invalid codec probe")
    if type(probe["nonce"]) is not str or re.fullmatch(r"[0-9a-f]{32}", probe["nonce"]) is None:
        raise ValueError("Invalid codec nonce")
    for key, shape, dtype in (("numeric", (1, 4), np.dtype("float32")), ("image", (1, 2, 3, 3), np.dtype("uint8"))):
        array = probe[key]
        if (
            type(array) is not np.ndarray
            or array.shape != shape
            or array.dtype != dtype
            or not np.isfinite(array).all()
        ):
            raise ValueError("Invalid codec array")
    if len(MsgSerializer.to_bytes(probe)) > CODEC_MAX_BYTES:
        raise ValueError("Codec probe byte limit")
    return probe


def validate_codec_echo(response, probe, expected_server_info):
    """Check exact echoed dtype/shape/bytes and server identity against a fresh challenge."""
    from gr00t.policy.server_client import MsgSerializer

    validate_codec_probe(probe)
    if type(response) is not dict or set(response) != {"server_info", "probe"}:
        raise ValueError("Invalid codec response")
    if validate_server_info(response["server_info"]) != validate_server_info(expected_server_info):
        raise ValueError("Policy identity changed")
    echoed = validate_codec_probe(response["probe"])
    if echoed["nonce"] != probe["nonce"] or any(
        echoed[key].tobytes() != probe[key].tobytes() for key in ("numeric", "image")
    ):
        raise ValueError("Codec bytes changed")
    if len(MsgSerializer.to_bytes(response)) > CODEC_MAX_BYTES:
        raise ValueError("Codec response byte limit")


def register_metadata_endpoints(server, policy, server_info):
    """Register provenance and guarded effects on the same native server/policy."""
    info = validate_server_info(server_info)
    model, processor = policy.model, policy.processor

    def get_server_info():
        if server.policy is not policy or policy.model is not model or policy.processor is not processor:
            raise ValueError("Loaded policy changed")
        modalities = validate_droid_modalities(policy.get_modality_config())
        if (
            canonical_metadata_digest(modalities) != info["modalities_sha256"]
            or native_serializer_sha256() != info["serializer_sha256"]
        ):
            raise ValueError("Loaded policy metadata changed")
        return dict(info)

    def codec_echo(probe):
        validate_codec_probe(probe)
        return {"server_info": get_server_info(), "probe": probe}

    def verified_call(expected_server_info, endpoint, data):
        """Check the receiving instance before dispatching a pinned policy effect."""
        if type(endpoint) is not str or endpoint not in {"get_action", "reset"}:
            raise ValueError("Invalid verified endpoint")
        fields = {"observation", "options"} if endpoint == "get_action" else {"options"}
        if type(data) is not dict or set(data) != fields:
            raise ValueError("Invalid verified data")
        if data["options"] is not None and type(data["options"]) is not dict:
            raise ValueError("Invalid verified options")
        if endpoint == "get_action" and type(data["observation"]) is not dict:
            raise ValueError("Invalid verified observation")
        if validate_server_info(expected_server_info) != get_server_info():
            raise ValueError("Policy identity changed")
        # Native dispatch is serial: no second RPC between this check and effect.
        return getattr(policy, endpoint)(**data)

    get_server_info()
    server.register_endpoint("get_server_info", get_server_info, requires_input=False)
    server.register_endpoint("codec_echo", codec_echo, requires_input=True)
    server.register_endpoint("verified_call", verified_call, requires_input=True)


def _load_policy(model_path, device):
    from huggingface_hub import constants

    if not constants.HF_HUB_OFFLINE:
        raise ValueError("Run the serving CLI in a fresh offline process")
    from gr00t.data.embodiment_tags import EmbodimentTag
    from gr00t.policy.gr00t_policy import Gr00tPolicy

    return Gr00tPolicy(embodiment_tag=EmbodimentTag.OXE_DROID, model_path=str(model_path), device=device, strict=True)


class _PreflightSocket:
    """Validate receive bytes before the unchanged native dispatch/decoder sees them."""

    def __init__(self, socket):
        self._socket = socket

    def __getattr__(self, name):
        return getattr(self._socket, name)

    def recv(self, *args, **kwargs):
        payload = self._socket.recv(*args, **kwargs)
        preflight_native_message(payload)
        return payload


def _close_native_resources(owner):
    """Close only the socket/context we own; N1.6 has no lifecycle methods."""
    if getattr(owner, "_arena_closed", False):
        return
    owner._arena_closed = True
    owner.running = False
    try:
        socket = getattr(owner, "socket", None)
        if socket is not None:
            socket.close(linger=0)
    finally:
        context = getattr(owner, "context", None)
        if context is not None:
            context.term()


class OwnedPolicyServer(PolicyServer):
    """Native N1.6 dispatch engine with first-party receive safety and lifecycle."""

    def __init__(self, policy, host="*", port=5555, api_token=None):
        import zmq

        try:
            super().__init__(policy, host=host, port=port, api_token=api_token)
            self.socket.setsockopt(zmq.MAXMSGSIZE, NATIVE_MAX_MESSAGE_BYTES)
            self.socket.setsockopt(zmq.LINGER, 0)
            self.socket = _PreflightSocket(self.socket)
        except BaseException:
            self.close()
            raise

    def close(self):
        _close_native_resources(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def _policy_server_type():
    return OwnedPolicyServer


def create_server(model_path, *, checkpoint_sha256, config_sha256, device="cuda:0", host="127.0.0.1", port=5555):
    """Load approved local artifacts offline, then bind and register the native server."""
    # Vendored GR00T can bypass actual weights in its explicitly test-only loader.
    if os.environ.get("GROOT_SKIP_HF_MODEL_WEIGHTS", "").strip().lower() not in {"", "0", "false", "no", "off"}:
        raise ValueError("Refusing test-only no-weight loading")
    # Set before importing transformers/HF; this wrapper never downloads artifacts.
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    artifacts = fingerprint_artifacts(model_path)
    if artifacts != {"checkpoint_sha256": checkpoint_sha256, "config_sha256": config_sha256}:
        raise ValueError("Policy artifacts are not approved")
    policy = _load_policy(Path(model_path).absolute(), device)
    if fingerprint_artifacts(model_path) != artifacts:
        raise ValueError("Policy artifacts changed during load")
    modalities = validate_droid_modalities(policy.get_modality_config())
    info = validate_server_info({
        "schema_version": 1,
        "instance_id": secrets.token_hex(16),
        "checkpoint_id": CHECKPOINT_ID,
        **artifacts,
        "embodiment": "OXE_DROID",
        "serializer_sha256": native_serializer_sha256(),
        "modalities_sha256": canonical_metadata_digest(modalities),
    })
    server = _policy_server_type()(policy, host=host, port=port, api_token=None)
    try:
        if hasattr(server, "socket"):
            import zmq

            server.socket.setsockopt(zmq.MAXMSGSIZE, NATIVE_MAX_MESSAGE_BYTES)
            server.socket.setsockopt(zmq.LINGER, 0)
        register_metadata_endpoints(server, policy, info)
    except BaseException:
        server.close()
        raise
    return server


def verify_native_connection(client, expected_server_info):
    """Run bounded native verification, serialized with asynchronous scheduler traffic."""
    with getattr(client, "_transport_lock", nullcontext()):
        return _verify_native_connection(client, expected_server_info)


def _verify_native_connection(client, expected_server_info):
    """Verify fresh native-codec/metadata reads on one connection, without inference.

    Callers own the deadline-bounded native client and its cleanup. This helper does
    not grant model approval: the exact expectation must originate from the worker's
    independently operator-pinned readiness check.
    """
    expected = validate_server_info(expected_server_info)
    if native_serializer_sha256() != expected["serializer_sha256"]:
        raise ValueError("Native serializer mismatch")
    if client.call_endpoint("ping", requires_input=False) != {"status": "ok", "message": "Server is running"}:
        raise ValueError("Invalid policy ping")
    before = validate_server_info(client.call_endpoint("get_server_info", requires_input=False))
    if before != expected:
        raise ValueError("Policy identity changed")
    native_modalities = client.call_endpoint("get_modality_config", requires_input=False)
    modalities = validate_droid_modalities(native_modalities)
    if canonical_metadata_digest(modalities) != expected["modalities_sha256"]:
        raise ValueError("Policy modalities changed")
    probe = make_codec_probe()
    response = client.call_endpoint("codec_echo", {"probe": probe})
    validate_codec_echo(response, probe, expected)
    after = validate_server_info(client.call_endpoint("get_server_info", requires_input=False))
    if after != expected:
        raise ValueError("Policy identity changed")
    client._verified_modalities = native_modalities
    return dict(after)


def verify_policy_identity(client, expected_server_info):
    """Lightweight pinned-instance check; server revalidates its bound policy metadata."""
    expected = validate_server_info(expected_server_info)
    observed = validate_server_info(client.call_endpoint("get_server_info", requires_input=False))
    if observed != expected:
        raise ValueError("Policy identity changed")
    return observed


class VerifiedPolicyClient(PolicyClient):
    """Native client that fails closed across reconnects and before releasing actions."""

    def __init__(self, *, expected_server_info, timeout_ms=15000, metadata_timeout_ms=3000, **kwargs):
        self._transport_lock = threading.RLock()
        self._expected_server_info = validate_server_info(expected_server_info)
        if type(timeout_ms) is not int or not 1 <= timeout_ms <= 300000:
            raise ValueError("Invalid inference timeout")
        if type(metadata_timeout_ms) is not int or not 1 <= metadata_timeout_ms <= 5000:
            raise ValueError("Invalid metadata timeout")
        self.metadata_timeout_ms = metadata_timeout_ms
        try:
            super().__init__(timeout_ms=timeout_ms, **kwargs)
            self.ensure_verified_connection()
        except BaseException:
            self.close()
            raise

    def ensure_verified_connection(self):
        """Run full codec handshake once per owned socket, never repin after recovery."""
        with self._transport_lock:
            socket = getattr(self, "socket", None)
            if socket is None or getattr(self, "_verified_socket", None) is not socket:
                verify_native_connection(self, self._expected_server_info)
                self._verified_socket = socket

    def verify_identity(self):
        """Check the pin before action release, doing full verification after recovery."""
        with self._transport_lock:
            socket = getattr(self, "socket", None)
            if socket is None or getattr(self, "_verified_socket", None) is not socket:
                self.ensure_verified_connection()
            else:
                verify_policy_identity(self, self._expected_server_info)

    def _init_socket(self):
        # N1.6 constructor/ping use this hook; our call_endpoint also owns recovery.
        import zmq

        self._verified_socket = None
        self._verified_modalities = None
        old = getattr(self, "socket", None)
        if old is not None:
            old.close(linger=0)
        self.socket = self.context.socket(zmq.REQ)
        self.socket.setsockopt(zmq.RCVTIMEO, self.timeout_ms)
        self.socket.setsockopt(zmq.SNDTIMEO, self.timeout_ms)
        self.socket.setsockopt(zmq.MAXMSGSIZE, NATIVE_MAX_MESSAGE_BYTES)
        self.socket.setsockopt(zmq.LINGER, 0)
        self.socket.connect(f"tcp://{self.host}:{self.port}")
        self.socket = _PreflightSocket(self.socket)
        # Every action/reset rechecks, including the first call on this new socket.

    def call_endpoint(self, endpoint, data=None, requires_input=True):
        import zmq

        with self._transport_lock:
            deadline = self.timeout_ms if endpoint == "get_action" else self.metadata_timeout_ms
            if endpoint in ("get_action", "reset"):
                data = {"expected_server_info": dict(self._expected_server_info), "endpoint": endpoint, "data": data}
                endpoint, requires_input = "verified_call", True
            self.socket.setsockopt(zmq.RCVTIMEO, deadline)
            self.socket.setsockopt(zmq.SNDTIMEO, deadline)
            old = self.socket
            try:
                return super().call_endpoint(endpoint, data, requires_input)
            except (zmq.ZMQError, ValueError):
                # N1.6 does not recover timeouts in call_endpoint. Newer SDKs may.
                if self.socket is old:
                    self._init_socket()
                raise

    def _get_action(self, observation, options=None):
        with self._transport_lock:
            self.verify_identity()
            response = super()._get_action(observation, options)
            self.verify_identity()
            return response

    def reset(self, options=None):
        with self._transport_lock:
            self.verify_identity()
            return super().reset(options)

    def close(self):
        with getattr(self, "_transport_lock", nullcontext()):
            _close_native_resources(self)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def __del__(self):
        with suppress(Exception):
            self.close()


def main(argv=None):
    """Serve a materialized approved local N1.6 model; no implicit Hub lookup."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model-path", required=True, type=Path)
    parser.add_argument("--checkpoint-sha256", default=os.environ.get("ARENA_GR00T_CHECKPOINT_SHA256"))
    parser.add_argument("--config-sha256", default=os.environ.get("ARENA_GR00T_CONFIG_SHA256"))
    parser.add_argument("--device", default="cuda:0")
    parser.add_argument("--host", choices=["127.0.0.1"], default="127.0.0.1")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument(
        "--fingerprint-only", action="store_true", help="Read local artifacts, print hashes, do not load/bind"
    )
    args = parser.parse_args(argv)
    if args.fingerprint_only:
        print(json.dumps(fingerprint_artifacts(args.model_path), sort_keys=True))
        return
    if not args.checkpoint_sha256 or not args.config_sha256:
        parser.error("Explicit operator checkpoint/config approval hashes are required")
    with create_server(
        args.model_path,
        checkpoint_sha256=args.checkpoint_sha256,
        config_sha256=args.config_sha256,
        device=args.device,
        host=args.host,
        port=args.port,
    ) as server:
        server.run()


if __name__ == "__main__":
    main()
