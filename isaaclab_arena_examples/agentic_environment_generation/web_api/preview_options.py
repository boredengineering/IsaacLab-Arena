# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Strict camera options shared by submission, catalogue lookup and rendering."""

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

View = Literal["isometric", "front", "side", "top"]
NodeId = Annotated[str, Field(pattern=r"^[A-Za-z0-9_-]{1,128}$")]


class RenderOptions(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)
    view: View = "isometric"
    resolution: Literal[512, 1024] = 1024
    asset_views: dict[NodeId, View] = Field(default_factory=dict, max_length=128)

    @field_validator("resolution", mode="before")
    @classmethod
    def integer_resolution(cls, value):
        if type(value) is not int:
            raise ValueError("Resolution must be an integer")
        return value


def normalized_options(options=None, canonical=None):
    """Return an independent normalized copy, checking overrides against frozen node IDs."""
    result = RenderOptions.model_validate({} if options is None else options).model_dump()
    if canonical is not None:
        nodes = [
            canonical["embodiment"],
            canonical["background"],
            *canonical.get("objects", []),
            *(canonical.get("object_references") or []),
        ]
        if set(result["asset_views"]) - {node["id"] for node in nodes}:
            raise ValueError("Camera overrides must reference validated asset node IDs")
    return result
