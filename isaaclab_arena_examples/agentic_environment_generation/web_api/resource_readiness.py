# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Observed GPU headroom, not a reservation or simulation-success guarantee."""

import fcntl
import os
import re
import selectors
import stat
import subprocess
import time

from .provider_security import worker_environment

VISIBILITY = ("CUDA_VISIBLE_DEVICES", "NVIDIA_VISIBLE_DEVICES")
RESOURCE_CODES = (
    "resource_unknown",
    "resource_headroom_observed",
    "resource_lease_busy",
    "resource_insufficient",
    "resource_device_changed",
    "resource_hidden",
    "resource_ambiguous",
)
_UUID = re.compile(r"GPU-[a-fA-F0-9]{8}(?:-[a-fA-F0-9]{4}){3}-[a-fA-F0-9]{12}\Z")
MAX_GPU_BYTES = 16384


def configuration():
    """Capture only server-provisioned budget, visibility and the actual execution lease."""
    from .snapshot_process import GPU_LEASE

    return {
        "min_free_mib": os.environ.get("ARENA_WORKBENCH_GPU_MIN_FREE_MIB"),
        "uuid": os.environ.get("ARENA_WORKBENCH_GPU_UUID"),
        "lease": str(GPU_LEASE),
        **{name: os.environ.get(name) for name in VISIBILITY},
    }


def query_gpu(deadline):
    """Read bounded nvidia-smi metadata under one total deadline, without a shell."""
    if time.monotonic() >= deadline:
        raise TimeoutError("GPU read deadline")
    environment = worker_environment(None)
    environment.update({name: os.environ[name] for name in VISIBILITY if name in os.environ})
    process = subprocess.Popen(
        [
            "nvidia-smi",
            "--query-gpu=index,uuid,memory.free,memory.total,mig.mode.current",
            "--format=csv,noheader,nounits",
        ],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        env=environment,
        bufsize=0,
    )
    try:
        output = bytearray()
        os.set_blocking(process.stdout.fileno(), False)
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("GPU read deadline")
                if not selector.select(min(remaining, 0.1)):
                    continue
                chunk = os.read(process.stdout.fileno(), MAX_GPU_BYTES + 1 - len(output))
                output.extend(chunk)
                if len(output) > MAX_GPU_BYTES:
                    raise ValueError("GPU metadata bound")
                if not chunk:
                    break
        if process.wait(timeout=max(0.001, deadline - time.monotonic())) != 0:
            raise ValueError("GPU metadata unavailable")
        return output.decode("ascii")
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=0.5)
        process.stdout.close()


def _device(text, config):
    if type(text) is not str or len(text.encode()) > MAX_GPU_BYTES:
        raise ValueError("GPU metadata bound")
    rows = []
    for line in text.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) != 5 or not parts[0].isascii() or not parts[0].isdigit() or not _UUID.fullmatch(parts[1]):
            raise ValueError("Invalid GPU metadata")
        if parts[4] not in ("Disabled", "[N/A]"):
            raise ValueError("Unverified GPU partitioning")
        if any(not p.isascii() or not p.isdigit() or len(p) > 10 for p in (parts[2], parts[3])):
            raise ValueError("Invalid GPU memory")
        index, uuid, free, total = int(parts[0]), parts[1], int(parts[2]), int(parts[3])
        if not 0 <= free <= total or total <= 0:
            raise ValueError("Invalid GPU memory")
        rows.append((index, uuid, free, total))
    if not rows or len({r[0] for r in rows}) != len(rows) or len({r[1] for r in rows}) != len(rows):
        raise ValueError("Ambiguous GPU metadata")
    for name in reversed(VISIBILITY):
        mask = config[name]
        if mask is None or (name == "NVIDIA_VISIBLE_DEVICES" and mask == "all"):
            continue
        if mask in ("", "none", "void", "-1"):
            return "resource_hidden", None
        tokens = mask.split(",")
        if len(set(tokens)) != len(tokens):
            return "resource_ambiguous", None
        # CUDA ordinal ordering is not nvidia-smi ordering. Only ordinal zero
        # with an already singleton device is unambiguous; otherwise require UUIDs.
        if name == "CUDA_VISIBLE_DEVICES" and any(not _UUID.fullmatch(t) for t in tokens):
            if tokens == ["0"] and len(rows) == 1:
                continue
            return "resource_ambiguous", None
        selected = [r for r in rows if r[1] in tokens or (name == "NVIDIA_VISIBLE_DEVICES" and str(r[0]) in tokens)]
        if len(selected) != len(tokens):
            return "resource_hidden", None
        rows = selected
    if config["uuid"] is not None:
        rows = [r for r in rows if r[1] == config["uuid"]]
    if not rows:
        return "resource_hidden", None
    if len(rows) != 1:
        return "resource_ambiguous", None
    return "resource_headroom_observed", rows[0]


def probe_gpu(config):
    """Inspect an existing lease read-only and sample the same visible GPU twice."""
    fd = None
    try:
        if type(config) is not dict or set(config) != {"min_free_mib", "uuid", "lease", *VISIBILITY}:
            return "resource_unknown"
        budget = config["min_free_mib"]
        if type(budget) is not str or not re.fullmatch(r"[1-9][0-9]{0,9}", budget):
            return "resource_unknown"
        if config["uuid"] is not None and (type(config["uuid"]) is not str or not _UUID.fullmatch(config["uuid"])):
            return "resource_unknown"
        if any(config[name] != os.environ.get(name) for name in VISIBILITY):
            return "resource_device_changed"
        if not os.path.isabs(config["lease"]):
            return "resource_unknown"
        fd = os.open(config["lease"], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or os.getuid() == 0:
            return "resource_unknown"
        try:
            # Shared/nonblocking read lock detects the actual cross-namespace flock;
            # never create a file, write bytes, or acquire an exclusive job lease.
            fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
        except BlockingIOError:
            return "resource_lease_busy"
        deadline = time.monotonic() + 3
        first_code, first = _device(query_gpu(deadline), config)
        if time.monotonic() >= deadline:
            return "resource_unknown"
        if first is None:
            return first_code
        second_code, second = _device(query_gpu(deadline), config)
        if time.monotonic() >= deadline:
            return "resource_unknown"
        if second is None or first[:2] != second[:2] or first[3] != second[3]:
            return "resource_device_changed"
        current = os.stat(config["lease"], follow_symlinks=False)
        if (current.st_dev, current.st_ino) != (info.st_dev, info.st_ino):
            return "resource_device_changed"
        if min(first[2], second[2]) < int(budget):
            return "resource_insufficient"
        return second_code
    except Exception:
        return "resource_unknown"
    finally:
        if fd is not None:
            os.close(fd)
