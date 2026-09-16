# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Bounded local evaluation evidence, never arbitrary worker paths in public receipts."""

import hashlib
import json
import math
import os
import stat
from pathlib import Path

from .evaluation_profiles import FIXED

ARTIFACT_NAMES = ("index.html", "episode_results_rank0.jsonl", "eval_telemetry.ttl")
MAX_ARTIFACT_BYTES = 8 * 1024 * 1024
MAX_TOTAL_BYTES = 16 * 1024 * 1024
MAX_RECEIPT_BYTES = 256 * 1024


def plain_json(value, *, limit=MAX_RECEIPT_BYTES):
    """Detach bounded finite plain JSON, refusing non-JSON types and excessive nesting."""
    nodes = 0

    def visit(item, depth=0):
        nonlocal nodes
        nodes += 1
        if depth > 20 or nodes > 32000:
            raise ValueError("Evaluation JSON exceeds bounds")
        if item is None or type(item) in (str, bool, int):
            return
        if type(item) is float and math.isfinite(item):
            return
        if type(item) is list:
            for child in item:
                visit(child, depth + 1)
            return
        if type(item) is dict and all(type(key) is str for key in item):
            for key, child in item.items():
                visit(key, depth + 1)
                visit(child, depth + 1)
            return
        raise ValueError("Evaluation JSON must be finite and plain")

    visit(value)
    encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode()
    if len(encoded) > limit:
        raise ValueError("Evaluation JSON exceeds bounds")
    return json.loads(encoded)


def read_confined(root, relative):
    """Read bounded regular bytes with descriptor-relative no-follow ancestor traversal."""
    root = Path(root).absolute()
    relative = Path(relative)
    if relative.is_absolute() or not relative.parts or any(p in (".", "..") for p in relative.parts):
        raise ValueError("Invalid evaluation artifact path")
    parts = (*root.parts[1:], *relative.parts)
    directory = os.open(root.anchor, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            next_directory = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
            os.close(directory)
            directory = next_directory
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
        with os.fdopen(fd, "rb") as source:
            info = os.fstat(source.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ARTIFACT_BYTES:
                raise ValueError("Invalid evaluation artifact")
            data = source.read(MAX_ARTIFACT_BYTES + 1)
            if len(data) > MAX_ARTIFACT_BYTES or len(data) != info.st_size:
                raise ValueError("Evaluation artifact changed or exceeds bounds")
            return data
    finally:
        os.close(directory)


def artifact_metadata(name, data):
    return {"name": name, "sha256": hashlib.sha256(data).hexdigest(), "size": len(data)}


def episode_counts(data):
    """Count actual recorder rows; missing/null/nonboolean success remains unknown."""
    rows = []
    for line in data.decode("utf-8").splitlines():
        if not line.strip():
            continue
        row = plain_json(json.loads(line))
        if type(row) is not dict:
            raise ValueError("Invalid episode record")
        rows.append(row)
    if not rows:
        return 0, None
    successes = [row.get("success") for row in rows]
    return len(rows), sum(successes) if all(type(value) is bool for value in successes) else None


def collect_result(inputs, root, completed):
    """Copy only callback-identified evidence into a fixed job-private artifact directory."""
    root = Path(root).absolute()
    output = Path(completed["output_dir"])
    if not output.is_absolute():
        output = Path.cwd() / output
    relative = output.relative_to(root / "output")
    if ".." in relative.parts or Path(completed["report_path"]).absolute() != output / "index.html":
        raise ValueError("Evaluation report is not the callback's report")
    if (
        type(completed.get("num_steps")) is not int
        or completed["num_steps"] != 1000
        or completed.get("num_episodes") is not None
    ):
        raise ValueError("Evaluation budget mismatch")
    metrics = plain_json(completed["metrics"], limit=128 * 1024)
    if metrics is not None and type(metrics) is not dict:
        raise ValueError("Invalid evaluation metrics")
    warnings = completed.get("warnings", [])
    if type(warnings) is not list or any(type(w) is not str for w in warnings):
        raise ValueError("Invalid evaluation warnings")
    # Harness diagnostic text can contain paths or runtime details. Keep it private;
    # the public warning describes the actual presence, not invented metrics.
    public_warnings = ["Evaluation harness reported warnings; check private runtime logs"] if warnings else []
    data_by_name = {}
    for name in ARTIFACT_NAMES:
        try:
            data_by_name[name] = read_confined(root, Path("output") / relative / name)
        except FileNotFoundError:
            if name != "eval_telemetry.ttl":
                raise
            public_warnings.append("Local telemetry artifact was not produced")
    if sum(map(len, data_by_name.values())) > MAX_TOTAL_BYTES or not data_by_name["index.html"]:
        raise ValueError("Missing or oversized evaluation report")
    episode_count, success_count = episode_counts(data_by_name["episode_results_rank0.jsonl"])
    if episode_count == 0:
        public_warnings.append("No completed-episode evidence was recorded")
    elif success_count is None:
        public_warnings.append("Success count unavailable: some episode records lack boolean success")
    if metrics is None:
        public_warnings.append("Evaluation metrics were not returned by the harness")
    artifacts = root / "artifacts"
    artifacts.mkdir(mode=0o700)
    for name, data in data_by_name.items():
        fd = os.open(artifacts / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as target:
            target.write(data)
    return plain_json({
        "schema_version": 1,
        "input_hash": inputs["input_hash"],
        "canonical_hash": inputs["canonical_hash"],
        "profile": inputs["profile"],
        "language_instruction": inputs["language_instruction"],
        **FIXED,
        "completed": True,
        "publication": "not_requested",
        "metrics": metrics,
        "episode_count": episode_count,
        "success_count": success_count,
        "artifacts": [artifact_metadata(name, data) for name, data in data_by_name.items()],
        "warnings": public_warnings,
    })


def job_root(state_dir, job_id):
    """Derive private storage from the journal identity, never a worker-provided path."""
    import re

    if type(job_id) is not str or not re.fullmatch(r"[a-f0-9]{32}", job_id):
        raise ValueError("Invalid evaluation job identity")
    return Path(state_dir).absolute() / "evaluations" / job_id


def validate_result(inputs, result):
    """Require the exact frozen profile and bounded completion evidence schema."""
    import re

    plain_json(result)
    expected = {
        "schema_version": 1,
        "input_hash": inputs["input_hash"],
        "canonical_hash": inputs["canonical_hash"],
        "profile": inputs["profile"],
        "language_instruction": inputs["language_instruction"],
        **FIXED,
        "completed": True,
        "publication": "not_requested",
    }
    fields = {*expected, "metrics", "episode_count", "success_count", "artifacts", "warnings"}
    if (
        type(result) is not dict
        or set(result) != fields
        or any(type(result[k]) is not type(v) or result[k] != v for k, v in expected.items())
    ):
        raise ValueError("Evaluation receipt does not match frozen inputs")
    count, success = result["episode_count"], result["success_count"]
    if (
        type(count) is not int
        or count < 0
        or (count == 0 and success is not None)
        or (success is not None and (type(success) is not int or not 0 <= success <= count))
    ):
        raise ValueError("Invalid evaluation episode counts")
    if result["metrics"] is not None and type(result["metrics"]) is not dict:
        raise ValueError("Invalid evaluation metrics")
    plain_json(result["metrics"], limit=128 * 1024)
    if type(result["warnings"]) is not list or any(
        type(w) is not str or len(w.encode()) > 4000 for w in result["warnings"]
    ):
        raise ValueError("Invalid evaluation warnings")
    rows = result["artifacts"]
    if type(rows) is not list or not 2 <= len(rows) <= len(ARTIFACT_NAMES):
        raise ValueError("Missing evaluation artifacts")
    names = set()
    for row in rows:
        if (
            type(row) is not dict
            or set(row) != {"name", "sha256", "size"}
            or type(row["name"]) is not str
            or row["name"] not in ARTIFACT_NAMES
            or row["name"] in names
            or type(row["sha256"]) is not str
            or not re.fullmatch(r"[a-f0-9]{64}", row["sha256"])
            or type(row["size"]) is not int
            or not 0 <= row["size"] <= MAX_ARTIFACT_BYTES
        ):
            raise ValueError("Invalid evaluation artifact metadata")
        names.add(row["name"])
    if not {"index.html", "episode_results_rank0.jsonl"} <= names or sum(row["size"] for row in rows) > MAX_TOTAL_BYTES:
        raise ValueError("Missing or oversized evaluation artifacts")


def screen_artifact(data, protect):
    """Apply current public policy to actual bytes, decoded entities and escape spellings."""
    import html

    from .public_records import _protect_yaml, screen_public_record

    if len(data) > MAX_ARTIFACT_BYTES:
        raise ValueError("Evaluation artifact exceeds bounds")
    text = data.decode("utf-8")
    protect(text)
    decoded = html.unescape(text)
    # Decode the complete bounded representation before chunking: escaped keys
    # and YAML line continuations can exceed any fixed overlap. The shared
    # guard unfolds/decodes the whole text even above its 256 KiB parser limit;
    # these transforms do not grow the artifact's bounded character count.
    _protect_yaml(decoded, protect)
    # Retain bounded recursive YAML screening in addition to the whole-text
    # escape guard, without increasing the shared single-string parser limit.
    width, overlap = 128 * 1024, 8192
    for offset in range(0, len(decoded), width - overlap):
        screen_public_record(decoded[offset : offset + width], protect)


def verify_result(root, inputs, result, protect):
    """Read every accepted artifact after owned-group cleanup and on each download."""
    from .public_records import screen_public_record

    validate_result(inputs, result)
    screen_public_record(result, protect)
    files = {}
    for row in result["artifacts"]:
        data = read_confined(root, Path("artifacts") / row["name"])
        if artifact_metadata(row["name"], data) != row:
            raise ValueError("Evaluation artifact identity mismatch")
        screen_artifact(data, protect)
        files[row["name"]] = data
    if not files["index.html"] or episode_counts(files["episode_results_rank0.jsonl"]) != (
        result["episode_count"],
        result["success_count"],
    ):
        raise ValueError("Evaluation episode evidence mismatch")
    return files
