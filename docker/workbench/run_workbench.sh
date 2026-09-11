#!/bin/sh
# Copyright (c) 2026, The Isaac Lab-Arena Project Developers.
# SPDX-License-Identifier: Apache-2.0
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 "$HERE/workbench.py" "$@"
