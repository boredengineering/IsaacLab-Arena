# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Decode retained Arena core episode records without fabricating completed trials."""

import hashlib
import json
import math
from dataclasses import dataclass

from pydantic import TypeAdapter

from .contracts import Identifier
from .policy_contracts import PolicyEpisode, PolicyTaskBinding, aggregate_policy_episodes


@dataclass(frozen=True)
class EpisodeRecordReadback:
    """Integrity of supplied bytes, not a native producer authenticity claim."""

    episodes: tuple[PolicyEpisode, ...]
    raw_sha256: str
    byte_count: int


def decode_episode_records(binding, raw, *, job_name, first_episode_index, reset_ids):
    """Map CoreEpisodeRecorder JSONL to exact runtime-observed reset identities.

    Args:
        binding: Frozen policy/task/environment binding.
        raw: Actual retained JSONL bytes, including empty incomplete attempts.
        job_name: Exact job name configured on the Arena episode recorder.
        first_episode_index: Observed environment episode index before the first action.
        reset_ids: Ordered identities of the prepared cohorts, including any unfinished last cohort.

    Returns:
        Completed episode evidence and the digest/size of all supplied raw bytes.
        The owner must separately retain and verify those bytes and completion witnesses.
    """
    binding = PolicyTaskBinding.model_validate(binding.model_dump())
    if type(raw) is not bytes or len(raw) > 2 * 1024 * 1024:
        raise ValueError("policy episode byte bound")
    if type(job_name) is not str or not 1 <= len(job_name) <= 128:
        raise ValueError("policy episode job binding required")
    if type(first_episode_index) is not int or first_episode_index < 0:
        raise ValueError("policy episode index required")
    if type(reset_ids) is not tuple or len(reset_ids) > binding.max_episodes:
        raise ValueError("policy reset coverage bound")
    for reset_id in reset_ids:
        TypeAdapter(Identifier).validate_python(reset_id)
    if len(set(reset_ids)) != len(reset_ids) or (reset_ids and reset_ids[0] != binding.reset_id):
        raise ValueError("policy reset identity mismatch")
    rows = raw.splitlines()
    if len(rows) > binding.max_episodes or len(rows) > len(reset_ids):
        raise ValueError("policy completed episode coverage mismatch")
    episodes = []

    def unique_object(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                raise ValueError("duplicate episode field")
            value[key] = item
        return value

    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("nonfinite episode number")
        return number

    for offset, line in enumerate(rows):
        try:
            row = json.loads(
                line, object_pairs_hook=unique_object, parse_float=finite_float, parse_constant=finite_float
            )
            if (
                type(row) is not dict
                or row.get("job_name") != job_name
                or type(row.get("env_id")) is not int
                or row["env_id"] != 0
                or type(row.get("episode_in_env")) is not int
                or row["episode_in_env"] != first_episode_index + offset
                or type(row.get("seed")) is not int
                or row["seed"] != binding.seed
                or row.get("language_instruction") != binding.instruction
                or "success" not in row
                or (row["success"] is not None and type(row["success"]) is not bool)
                or type(row.get("episode_length")) is not int
                or row["episode_length"] <= 0
            ):
                raise ValueError
            episode_id = hashlib.sha256(
                json.dumps([binding.digest(), first_episode_index + offset], separators=(",", ":")).encode()
            ).hexdigest()
            episodes.append(
                PolicyEpisode(
                    binding_digest=binding.digest(),
                    episode_id=episode_id,
                    reset_id=reset_ids[offset],
                    seed=binding.seed,
                    success=row["success"],
                )
            )
        except (ValueError, TypeError, KeyError, RecursionError):
            raise ValueError("policy episode record mismatch") from None
    episodes = tuple(episodes)
    aggregate_policy_episodes(binding, episodes)
    return EpisodeRecordReadback(episodes, hashlib.sha256(raw).hexdigest(), len(raw))
