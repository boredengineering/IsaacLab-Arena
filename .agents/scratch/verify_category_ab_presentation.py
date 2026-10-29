"""Verify the presentation's historical result tables against the recounted inventory."""

import json
import re
from pathlib import Path
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[2]
DECK = ROOT / ".agents/references/presentations/category_a_b_manipulation_experiments.md"


def main():
    inventory = json.loads(DECK.with_name("category_a_b_run_inventory.json").read_text())
    by_path = {row["run_path"]: row for row in inventory["runs"]}
    text = DECK.read_text()
    fenced = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            fenced = not fenced
    assert not fenced, "Unclosed Markdown fence"
    verified = set()
    for line in text.splitlines():
        if not line.startswith("|") or "/episode_results_rank0.jsonl)" not in line:
            continue
        cells = [cell.strip().replace("**", "") for cell in line.strip("|").split("|")]
        target = re.search(r"\]\(([^)]+/episode_results_rank0.jsonl)\)", cells[1]).group(1)
        source = (DECK.parent / target).resolve()
        key = str(source.parent.relative_to(ROOT))
        assert source.exists() and key in by_path
        row = by_path[key]
        assert row["period"] == "historical" and row["episodes"] > 0
        counts = [tuple(map(int, re.search(r"(\d+)/(\d+)", cell).groups())) for cell in cells[2:6]]
        expected = [(row["success_flags"], row["episodes"]),
                    (row["lift_event_episodes"], row["episodes"]),
                    (row["progress_complete_episodes"], row["episodes"]),
                    (row["success_and_lift"], row["lift_event_episodes"])]
        assert counts == expected, (key, counts, expected)
        for index, rate in ((2, row["success_rate"]), (5, row["success_given_lift"])):
            shown = re.search(r"\(([\d.]+)%\)", cells[index])
            assert shown is not None and abs(float(shown.group(1)) - 100 * rate) <= 0.051, (key, index)
        actual_median = None if cells[6] == "—" else float(cells[6])
        assert actual_median == row["median_episode_steps_success_flags"], key
        assert key not in verified
        verified.add(key)
    expected_runs = {r["run_path"] for r in inventory["runs"] if r["period"] == "historical" and r["episodes"] > 0}
    assert verified == expected_runs and len(verified) == 17
    missing = []
    checked_links = 0
    for target in re.findall(r"\]\(([^)]+)\)", text):
        parsed = urlparse(target)
        if parsed.scheme in ("http", "https") or target.startswith("#"):
            continue
        if parsed.scheme == "file":
            path = Path(unquote(parsed.path))
        elif not parsed.scheme:
            path = (DECK.parent / unquote(parsed.path)).resolve()
        else:
            continue
        checked_links += 1
        if not path.exists():
            missing.append(target)
    assert not missing, missing
    assert "docker run -d" not in text, "Uncorrected old server launch recipe"
    assert "xhost +local" not in text, "Uncorrected broad X11 access recipe"
    print(json.dumps({"verified_historical_table_rows": len(verified),
                      "local_links_checked": checked_links, "missing_local_links": missing,
                      "markdown_fences": "balanced", "inventory": inventory["counts"]}, indent=2))


if __name__ == "__main__":
    main()
