# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Select one embedded A/B scenario; never dispatch a workload.

Run with --print for the selected scenario and original prompt as readable JSON.
Selections exclude the last ID stored in --state, including across processes.
Replay requires the seed, catalogue hash and previous ID saved in the manifest.
The seed controls scenario selection only, not generation, simulation or policy.
Historical notes are retained as data, never treated as runtime configuration.
"""

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import secrets
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOGUE = ROOT / ".agents/references/agentic_env_generation/env_gen_test.md"
DEFAULT_STATE = ROOT / "outputs/workflow/scenario-selection-state.json"
EXPECTED_IDS = tuple(f"{category}{number}" for category in "AB" for number in range(1, 6))
MAX_SOURCE_BYTES = 1024 * 1024


def _scenario(scenario_id, name, source, target, prompt):
    return dict(
        scenario_id=scenario_id,
        category=scenario_id[0],
        test_name=name,
        source_object=source,
        target_container=target,
        source_sector="front_right",
        target_sector="front_left",
        embodiment="droid_abs_joint_pos",
        background_options=(
            ["maple_table_robolab"]
            if scenario_id.startswith("A")
            else ["kitchen", "packing_table", "maple_table_robolab"]
        ),
        policy_model="nvidia/GR00T-N1.6-DROID",
        prompt=prompt,
    )


# Standalone prompt catalogue, transcribed from env_gen_test.md.
# Do not silently rename assets or substitute B2's purple crate with a grey bin.
SCENARIOS = (
    _scenario(
        "A1",
        "Apple to Wooden Bowl",
        "apple_01_objaverse_robolab",
        "wooden_bowl_hot3d_robolab",
        "Pick up the red apple from the front right of the maple table and place it into the wooden bowl on the front"
        " left.",
    ),
    _scenario(
        "A2",
        "Banana to Large Plate",
        "banana_ycb_robolab",
        "plate_large_vomp_robolab",
        "Grasp the yellow banana from the right side of the table and set it onto the white ceramic plate on the left.",
    ),
    _scenario(
        "A3",
        "Lemon to Clay Plate",
        "lemon_01_fruits_veggies_robolab",
        "clay_plates_hot3d_robolab",
        "Pick up the fresh lemon from the front right and carefully place it on the clay plate at the front left.",
    ),
    _scenario(
        "A4",
        "Avocado to Serving Bowl",
        "avocado01_fruits_veggies_robolab",
        "serving_bowl_vomp_robolab",
        "Pick the green avocado from the right sector and place it inside the serving bowl on the left.",
    ),
    _scenario(
        "A5",
        "Red Bell Pepper to Blue Bin",
        "red_bell_pepper_objaverse_robolab",
        "bin_b03_vomp_robolab",
        "Grasp the red bell pepper from the front right table sector and drop it into the blue bin on the front left.",
    ),
    _scenario(
        "B1",
        "Tomato Soup to Blue Bin",
        "tomato_soup_can_ycb_robolab",
        "bin_b03_vomp_robolab",
        "Pick up the red tomato soup can from the front right of the counter and deposit it into the blue sorting bin.",
    ),
    _scenario(
        "B2",
        "Mustard Bottle to Purple Crate",
        "mustard_bottle_hot3d_robolab",
        "purple_crate",
        "Grasp the yellow mustard bottle from the right side and place it upright inside the purple storage crate.",
    ),
    _scenario(
        "B3",
        "Cracker Box to Brown Box",
        "cracker_box",
        "brown_box",
        "Pick up the Cheez-It cracker box from the packing table and place it into the brown cardboard box.",
    ),
    _scenario(
        "B4",
        "Spam Can to Grey Bin",
        "spam_can_ycb_robolab",
        "grey_bin_robolab",
        "Pick the blue Spam can from the right section and drop it into the grey bin on the left.",
    ),
    _scenario(
        "B5",
        "Tuna Can to Small Plate",
        "tuna_can_ycb_robolab",
        "plate_small_vomp_robolab",
        "Pick up the tuna can from the front right sector and set it onto the small plate on the front left.",
    ),
)


def _unquote(cell, marker):
    if not cell.startswith(marker) or not cell.endswith(marker) or len(cell) <= 2 * len(marker):
        raise ValueError("Unexpected catalogue cell format")
    return cell[len(marker) : -len(marker)]


def read_catalogue(path) -> tuple[str, list[dict]]:
    """Return detached embedded records, or explicitly requested Markdown data."""
    if path is None:
        if tuple(row["scenario_id"] for row in SCENARIOS) != EXPECTED_IDS:
            raise ValueError("Embedded catalogue must contain exactly ordered A1-A5 and B1-B5")
        raw = json.dumps(SCENARIOS, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(raw).hexdigest(), json.loads(raw)
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_SOURCE_BYTES + 1)
    if len(raw) > MAX_SOURCE_BYTES:
        raise ValueError("Catalogue exceeds source limit")
    text = raw.decode("utf-8")
    rows, headings, notes = {}, {}, {}
    category = None
    for number, line in enumerate(text.splitlines(), 1):
        if line.startswith("### "):
            match = re.match(r"^### .*Category ([AB]): .+$", line)
            category = match.group(1) if match else None
            if category:
                if category in headings:
                    raise ValueError("Duplicate category heading")
                headings[category], notes[category] = line, []
        if category and line.startswith("* **"):
            notes[category].append(line)
        match = re.match(r"^\| \*\*([AB][0-9]+)\*\* \|", line)
        if not match:
            continue
        scenario_id = match.group(1)
        if category != scenario_id[0] or scenario_id not in EXPECTED_IDS or scenario_id in rows:
            raise ValueError("Unexpected or duplicate scenario identity")
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 7:
            raise ValueError("Unexpected scenario columns")
        rows[scenario_id] = dict(
            scenario_id=scenario_id,
            category=category,
            test_name=_unquote(cells[1], "**"),
            source_object=_unquote(cells[2], "`"),
            target_container=_unquote(cells[3], "`"),
            source_sector=_unquote(cells[4], "`"),
            target_sector=_unquote(cells[5], "`"),
            prompt=_unquote(_unquote(cells[6], "*"), '"'),
            source_line=number,
            source_row=line,
            category_heading=headings[category],
            category_notes=notes[category].copy(),
        )
    if set(rows) != set(EXPECTED_IDS):
        raise ValueError("Expected exactly A1-A5 and B1-B5")
    return hashlib.sha256(raw).hexdigest(), [rows[key] for key in EXPECTED_IDS]


def select(catalogue, seed, *, expected_source_sha256=None, previous=None) -> dict:
    """Draw uniformly excluding the previous ID; seed, source and previous replay it."""
    if type(seed) is not int or not 0 <= seed < 2**128:
        raise ValueError("Selection seed must be an unsigned 128-bit integer")
    source_hash, rows = read_catalogue(catalogue)
    if expected_source_sha256 is not None and source_hash != expected_source_sha256:
        raise ValueError("Catalogue digest changed; replay refused")
    if previous is not None and previous not in EXPECTED_IDS:
        raise ValueError("Unknown previous scenario")
    eligible = [i for i, row in enumerate(rows) if row["scenario_id"] != previous]
    index = eligible[random.Random(seed).randrange(len(eligible))]
    return dict(
        schema_version=1,
        source=dict(
            path=str(Path(catalogue).resolve()) if catalogue is not None else str(Path(__file__).resolve()),
            kind="markdown" if catalogue is not None else "embedded_catalogue",
            hash_basis="file_bytes" if catalogue is not None else "canonical_catalogue_json",
            sha256=source_hash,
        ),
        selection=dict(
            seed=seed,
            algorithm="python-random-exclude-previous-v2",
            python_version=sys.version.split()[0],
            pool_size=len(rows),
            eligible_count=len(eligible),
            previous_scenario_id=previous,
            index=index,
            draw_number=index + 1,
        ),
        catalogue=rows,
        selected=rows[index],
        execution=dict(status="not_started", run_id=None, reason="selection_only"),
        limitations=[
            "Selection seed is not a model, simulation or policy seed.",
            "Historical policy ports, geometry and asset identifiers require runtime validation.",
            "The catalogue B2 prompt specifies purple_crate, not a grey-bin substitution.",
            "This manifest neither authorizes nor invokes simulation, models, retrieval or publication.",
        ],
    )


def _read_previous(path):
    if not path.exists():
        return None
    with path.open(encoding="utf-8") as stream:
        state = json.loads(stream.read(4097))
    if (
        type(state) is not dict
        or set(state) != {"schema_version", "previous_scenario_id"}
        or type(state["schema_version"]) is not int
        or state["schema_version"] != 1
        or state["previous_scenario_id"] not in EXPECTED_IDS
    ):
        raise ValueError("Invalid selection history; refusing to reset it")
    return state["previous_scenario_id"]


def _save_previous(path, scenario_id):
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent, delete=False) as stream:
            temporary = Path(stream.name)
            json.dump(dict(schema_version=1, previous_scenario_id=scenario_id), stream)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalogue", type=Path, help="Optional Markdown override; default is embedded scenarios")
    parser.add_argument("--seed", type=int)
    parser.add_argument("--expected-source-sha256", help="Refuse replay if the notes have changed")
    parser.add_argument("--output", type=Path, help="Exclusive manifest path; default is a new file beside state")
    parser.add_argument("--state", type=Path, default=DEFAULT_STATE, help="Persistent previous-selection file")
    parser.add_argument("--previous", choices=EXPECTED_IDS, help="Bootstrap a new history with a prior ID")
    parser.add_argument("--print", dest="print_scenario", action="store_true", help="Print scenario and prompt as JSON")
    args = parser.parse_args(argv)
    seed = args.seed if args.seed is not None else secrets.randbits(128)
    output = args.output or args.state.parent / "scenario-selections" / (secrets.token_hex(12) + ".json")
    if output.resolve() == args.state.resolve():
        raise ValueError("Output and history must be different files")
    args.state.parent.mkdir(parents=True, exist_ok=True)
    # Serialize read/draw/save across agents using the same history. Printing is
    # outside the lock, but only after the selected ID has been saved.
    with args.state.with_name(args.state.name + ".lock").open("a") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        previous = _read_previous(args.state)
        if args.previous is not None:
            if previous is not None and previous != args.previous:
                raise ValueError("Explicit previous ID conflicts with selection history")
            previous = args.previous
        result = select(args.catalogue, seed, expected_source_sha256=args.expected_source_sha256, previous=previous)
        output.parent.mkdir(parents=True, exist_ok=True)
        with output.open("x", encoding="utf-8") as stream:
            json.dump(result, stream, ensure_ascii=False, indent=2, allow_nan=False)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _save_previous(args.state, result["selected"]["scenario_id"])
    printed = dict(
        output=str(output.resolve()),
        scenario_id=result["selected"]["scenario_id"],
        seed=seed,
        execution_status="not_started",
    )
    if args.print_scenario:
        printed.update(
            scenario=result["selected"],
            selection=result["selection"],
            prompt_guidance=(
                "Preserve this original prompt; record improvements separately, retaining task and asset identity."
            ),
        )
    print(json.dumps(printed, ensure_ascii=False, indent=2 if args.print_scenario else None))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
