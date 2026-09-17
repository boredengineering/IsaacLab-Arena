# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Read-only fixed-target policy verification; never infer or reset a shared policy."""

import os
import re
import time

from .policy_endpoint import LEGACY_GR00T_PORT, validate_gr00t_port


class MetadataPeer:
    """Own one short-lived REQ context at the fixed GR00T metadata target."""

    def __init__(self, *, port=LEGACY_GR00T_PORT):
        self.port = validate_gr00t_port(port)

    def __enter__(self):
        import zmq

        self.context = zmq.Context()
        self.socket = None
        self.deadline = time.monotonic() + 4
        self.calls = 0
        try:
            self.socket = self.context.socket(zmq.REQ)
            self.socket.setsockopt(zmq.LINGER, 0)
            self.socket.setsockopt(zmq.MAXMSGSIZE, MAX_METADATA_BYTES)
            self.socket.connect(f"tcp://127.0.0.1:{self.port}")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def call(self, endpoint):
        import msgpack
        import zmq

        if endpoint not in ("ping", "get_modality_config", "get_server_info") or self.calls >= 4:
            raise ValueError("Unsupported metadata RPC")
        remaining = min(750, int((self.deadline - time.monotonic()) * 1000))
        if remaining <= 0:
            raise TimeoutError("Metadata deadline exceeded")
        self.calls += 1
        self.socket.setsockopt(zmq.SNDTIMEO, remaining)
        self.socket.setsockopt(zmq.RCVTIMEO, remaining)
        self.socket.send(msgpack.packb({"endpoint": endpoint}))
        return decode_metadata(self.socket.recv())

    def __exit__(self, *_):
        try:
            if self.socket is not None:
                self.socket.close(0)
        finally:
            self.context.term()


MAX_METADATA_BYTES = 64 * 1024


def decode_metadata(payload):
    """Decode bounded plain MessagePack without pickle, ndarray or extension hooks."""
    import msgpack

    def pairs(items):
        value = {}
        for key, item in items:
            if type(key) is not str or key in value:
                raise ValueError("Invalid metadata map")
            value[key] = item
        markers = {"__ModalityConfig__", "__ModalityConfig_class__"} & value.keys()
        if markers:
            import json

            if len(markers) != 1 or set(value) != markers | {"as_json"} or value[next(iter(markers))] is not True:
                raise ValueError("Invalid modality wrapper")
            encoded = value["as_json"]
            if type(encoded) in (str, bytes):
                if len(encoded) > 16384:
                    raise ValueError("Modality JSON exceeds bound")
                value["as_json"] = json.loads(encoded, object_pairs_hook=pairs, parse_constant=reject_extension)
        return value

    def reject_extension(*_):
        raise ValueError("Invalid metadata extension")

    def plain(value, depth=0):
        if depth > 16:
            raise ValueError("Metadata nesting exceeds bound")
        if type(value) is dict:
            if any(key in value for key in ("nd", "__ndarray_class__", "as_npy")):
                raise ValueError("Array metadata is not supported")
            for item in value.values():
                plain(item, depth + 1)
        elif type(value) is list:
            for item in value:
                plain(item, depth + 1)
        elif value is not None and type(value) not in (str, bool, int):
            raise ValueError("Invalid metadata scalar")

    if type(payload) is not bytes or not 0 < len(payload) <= MAX_METADATA_BYTES:
        raise ValueError("Metadata exceeds bound")
    try:
        result = msgpack.unpackb(
            payload,
            raw=False,
            strict_map_key=True,
            object_pairs_hook=pairs,
            ext_hook=reject_extension,
            max_str_len=8192,
            max_bin_len=16384,
            max_array_len=128,
            max_map_len=64,
            max_ext_len=0,
        )
        plain(result)
        return result
    except Exception:
        raise ValueError("Invalid policy metadata") from None


def decode_codec_reply(payload, native_decoder):
    """Validate either native array wire format before its allocation decoder runs."""
    from isaaclab_arena.agentic_environment_generation.policy_contract import (
        native_array_metadata,
        preflight_native_message,
        validate_server_info,
    )

    try:
        value = preflight_native_message(payload, max_bytes=4096, max_array_bytes=34)
        if type(value) is not dict or set(value) != {"server_info", "probe"}:
            raise ValueError("Invalid codec response")
        validate_server_info(value["server_info"])
        probe = value["probe"]
        if type(probe) is not dict or set(probe) != {"nonce", "numeric", "image"}:
            raise ValueError("Invalid codec probe")
        if type(probe["nonce"]) is not str or not re.fullmatch(r"[a-f0-9]{32}", probe["nonce"]):
            raise ValueError("Invalid codec nonce")
        for key, shape, dtype, size in (
            ("numeric", [1, 4], "<f4", 16),
            ("image", [1, 2, 3, 3], "|u1", 18),
        ):
            layout = native_array_metadata(probe[key], max_array_bytes=34)
            if layout != {"shape": shape, "dtype": dtype, "bytes": size}:
                raise ValueError("Unsupported native array wire contract")
    except Exception:
        raise ValueError("Invalid bounded codec response") from None
    return native_decoder(payload)


class NativeCodecPeer(MetadataPeer):
    """Run the native connection verifier through strictly bounded read-only RPCs."""

    def __init__(self, serializer, *, port=LEGACY_GR00T_PORT):
        super().__init__(port=port)
        self.serializer = serializer

    def call_endpoint(self, endpoint, data=None, requires_input=True):
        import zmq

        codec = endpoint == "codec_echo"
        if (
            endpoint not in ("ping", "get_server_info", "get_modality_config", "codec_echo")
            or self.calls >= 5
            or requires_input is not codec
            or (not codec and data is not None)
            or (codec and (type(data) is not dict or set(data) != {"probe"}))
        ):
            raise ValueError("Unsupported native readiness RPC")
        remaining = min(500, int((self.deadline - time.monotonic()) * 1000))
        if remaining <= 0:
            raise TimeoutError("Native verification deadline exceeded")
        self.calls += 1
        frame = {"endpoint": endpoint}
        if codec:
            frame["data"] = data
        encoded = self.serializer.to_bytes(frame)
        if len(encoded) > 4096:
            raise ValueError("Native verification request exceeds bound")
        self.socket.setsockopt(zmq.SNDTIMEO, remaining)
        self.socket.setsockopt(zmq.RCVTIMEO, remaining)
        self.socket.send(encoded)
        reply = self.socket.recv()
        return decode_codec_reply(reply, self.serializer.from_bytes) if codec else decode_metadata(reply)


def native_components():
    """Import the real native codec/helper only in the worker's explicit check path."""
    from gr00t.policy.server_client import MsgSerializer

    from isaaclab_arena_gr00t.policy.serving_metadata import verify_native_connection

    return MsgSerializer, verify_native_connection


def verify_native_transport(info, *, port=LEGACY_GR00T_PORT):
    """Verify same-codec synthetic numeric/image bytes without calling the model."""
    serializer, verify = native_components()
    with NativeCodecPeer(serializer, port=port) as client:
        verified = verify(client, info)
    return verified == info


def probe_gr00t(expectations, *, port=LEGACY_GR00T_PORT, transport_probe=None):
    """Distinguish protocol, operator-pinned model and native transport evidence."""
    from isaaclab_arena.agentic_environment_generation.policy_contract import (
        canonical_metadata_digest,
        validate_droid_modalities,
        validate_server_info,
    )

    port = validate_gr00t_port(port)
    result = {
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
    try:
        with MetadataPeer(port=port) as peer:
            if peer.call("ping") != {"status": "ok", "message": "Server is running"}:
                return result
            try:
                modalities = validate_droid_modalities(peer.call("get_modality_config"))
            except ValueError:
                result["policy_protocol"] = {
                    "status": "mismatch",
                    "code": "policy_modality_mismatch",
                }
                result["policy_model"] = {
                    "status": "mismatch",
                    "code": "policy_modality_mismatch",
                }
                return result
            result["policy_protocol"] = {
                "status": "passed",
                "code": "policy_protocol_available",
            }
            info = validate_server_info(peer.call("get_server_info"))
            if expectations is None:
                result["policy_model"] = {
                    "status": "not_checked",
                    "code": "policy_expectation_missing",
                }
                return result
            try:
                if type(expectations) is not dict or set(expectations) != {
                    "checkpoint_sha256",
                    "config_sha256",
                }:
                    raise ValueError("Invalid expectations")
                info = validate_server_info(info, **expectations)
                if info["modalities_sha256"] != canonical_metadata_digest(modalities):
                    raise ValueError("Modality digest mismatch")
            except ValueError:
                result["policy_model"] = {
                    "status": "mismatch",
                    "code": "policy_model_mismatch",
                }
                return result
            transport = False
            try:
                transport = (transport_probe or verify_native_transport)(info, port=port) is True
            except Exception:
                transport = False
            # A restart during the read or codec check invalidates every identity claim.
            if validate_server_info(peer.call("get_server_info")) != info:
                result["policy_model"] = {
                    "status": "mismatch",
                    "code": "policy_instance_mismatch",
                }
                return result
            result["policy_model"] = {
                "status": "passed",
                "code": "policy_model_verified",
            }
            if transport:
                result["policy_transport"] = {
                    "status": "passed",
                    "code": "policy_transport_verified",
                }
            result["server_info"] = info
            result["evidence"] = {
                "profile": "gr00t-droid",
                "expected_checkpoint": info["checkpoint_id"],
                **{
                    key: info[key]
                    for key in (
                        "instance_id",
                        "checkpoint_sha256",
                        "config_sha256",
                        "serializer_sha256",
                        "modalities_sha256",
                    )
                },
                "inference": "not_run",
            }
    except Exception:
        # Remote errors and unconfirmed socket cleanup invalidate earlier evidence.
        result["policy_model"] = {
            "status": "unavailable",
            "code": "policy_metadata_unavailable",
        }
        result["policy_transport"] = {
            "status": "not_checked",
            "code": "policy_transport_unverified",
        }
        result["server_info"] = result["evidence"] = None
    return result


def validate_probe_result(value):
    """Require exact code/status pairs and bind public evidence to validated metadata."""
    allowed = {
        "policy_protocol": {
            ("unavailable", "policy_protocol_unavailable"),
            ("mismatch", "policy_modality_mismatch"),
            ("passed", "policy_protocol_available"),
        },
        "policy_model": {
            ("unavailable", "policy_metadata_unavailable"),
            ("not_checked", "policy_expectation_missing"),
            ("mismatch", "policy_modality_mismatch"),
            ("mismatch", "policy_model_mismatch"),
            ("mismatch", "policy_instance_mismatch"),
            ("passed", "policy_model_verified"),
        },
        "policy_transport": {
            ("not_checked", "policy_transport_unverified"),
            ("passed", "policy_transport_verified"),
        },
    }
    if type(value) is not dict or set(value) != {*allowed, "evidence", "server_info"}:
        raise ValueError("Invalid policy receipt")
    for key, pairs in allowed.items():
        row = value[key]
        if (
            type(row) is not dict
            or set(row) != {"status", "code"}
            or type(row["status"]) is not str
            or type(row["code"]) is not str
            or (row["status"], row["code"]) not in pairs
        ):
            raise ValueError("Invalid policy receipt")
    if value["policy_model"]["status"] != "passed":
        if (
            value["evidence"] is not None
            or value["server_info"] is not None
            or value["policy_transport"]["status"] == "passed"
        ):
            raise ValueError("Unverified policy evidence")
    else:
        from isaaclab_arena.agentic_environment_generation.policy_contract import validate_server_info

        info = validate_server_info(value["server_info"])
        expected = {
            "profile": "gr00t-droid",
            "expected_checkpoint": info["checkpoint_id"],
            **{
                key: info[key]
                for key in (
                    "instance_id",
                    "checkpoint_sha256",
                    "config_sha256",
                    "serializer_sha256",
                    "modalities_sha256",
                )
            },
            "inference": "not_run",
        }
        if value["policy_protocol"]["status"] != "passed" or value["evidence"] != expected:
            raise ValueError("Policy evidence mismatch")
    return value


def expected_hashes():
    """Require literal operator pins, never learn expectations from a remote reply."""
    values = {
        key: os.environ.get(name)
        for key, name in (
            ("checkpoint_sha256", "ARENA_GR00T_CHECKPOINT_SHA256"),
            ("config_sha256", "ARENA_GR00T_CONFIG_SHA256"),
        )
    }
    if any(type(value) is not str or re.fullmatch(r"[a-f0-9]{64}", value) is None for value in values.values()):
        raise ValueError("policy_expectation_missing")
    return values
