#!/usr/bin/env python3
"""Download pi05_droid_jointpos weights from public GCS bucket directly to local cache.

Target directory: /root/.cache/openpi/openpi-assets-simeval/pi05_droid_jointpos
Total size: ~11.58 GB across 26 objects.
"""

import concurrent.futures
import json
import os
import pathlib
import sys
import time
import urllib.parse
import urllib.request

BUCKET_NAME = "openpi-assets-simeval"
PREFIX = "pi05_droid_jointpos/"
TARGET_DIR = pathlib.Path(os.environ.get("OPENPI_CACHE_DIR", "/root/.cache/openpi")) / BUCKET_NAME

CHUNK_SIZE = 8 * 1024 * 1024  # 8 MB chunks


def get_gcs_items(bucket: str, prefix: str):
    url = f"https://storage.googleapis.com/storage/v1/b/{bucket}/o?prefix={urllib.parse.quote(prefix)}"
    req = urllib.request.Request(url, headers={"User-Agent": "IsaacLab-Arena-Downloader/1.0"})
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
    return data.get("items", [])


def download_item(item: dict, base_dir: pathlib.Path) -> tuple[str, int, float]:
    name = item["name"]
    expected_size = int(item["size"])
    dest_path = base_dir / name
    dest_path.parent.mkdir(parents=True, exist_ok=True)

    # Check if already downloaded and complete
    if dest_path.exists() and dest_path.stat().st_size == expected_size:
        return (name, expected_size, 0.0)

    partial_path = dest_path.with_suffix(dest_path.suffix + ".partial")
    encoded_name = urllib.parse.quote(name, safe="")
    media_url = f"https://storage.googleapis.com/download/storage/v1/b/{BUCKET_NAME}/o/{encoded_name}?alt=media"

    t0 = time.time()
    req = urllib.request.Request(media_url, headers={"User-Agent": "IsaacLab-Arena-Downloader/1.0"})
    with urllib.request.urlopen(req) as resp, open(partial_path, "wb") as f:
        while True:
            chunk = resp.read(CHUNK_SIZE)
            if not chunk:
                break
            f.write(chunk)

    downloaded_size = partial_path.stat().st_size
    if downloaded_size != expected_size:
        partial_path.unlink(missing_ok=True)
        raise RuntimeError(f"Corrupt download for {name}: expected {expected_size} bytes, got {downloaded_size}")

    partial_path.replace(dest_path)
    # Ensure readable by containers and non-root users
    os.chmod(dest_path, 0o666)
    duration = max(time.time() - t0, 0.001)
    return (name, expected_size, duration)


def main():
    print(f"Querying public GCS catalog for gs://{BUCKET_NAME}/{PREFIX} ...")
    items = get_gcs_items(BUCKET_NAME, PREFIX)
    if not items:
        print("ERROR: No items found in GCS prefix!")
        sys.exit(1)

    total_bytes = sum(int(item["size"]) for item in items)
    print(f"Found {len(items)} objects totaling {total_bytes / (1024**3):.2f} GB.")
    print(f"Destination: {TARGET_DIR}")

    TARGET_DIR.mkdir(parents=True, exist_ok=True)

    completed_bytes = 0
    t_start = time.time()

    # Download in parallel using ThreadPoolExecutor
    # 4 workers avoids throttling while saturating standard gigabit pipe
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_item = {executor.submit(download_item, item, TARGET_DIR): item for item in items}
        for future in concurrent.futures.as_completed(future_to_item):
            item = future_to_item[future]
            name, size, dur = future.result()
            completed_bytes += size
            pct = (completed_bytes / total_bytes) * 100
            speed_mb = (size / (1024 * 1024)) / dur if dur > 0 else 0
            status = "CACHED" if dur == 0 else f"{speed_mb:.1f} MB/s"
            print(f"[{pct:5.1f}%] {name} ({size / (1024*1024):.2f} MB) -> {status}")

    total_elapsed = time.time() - t_start
    overall_speed = (total_bytes / (1024 * 1024)) / max(total_elapsed, 0.001)
    print(f"\nAll {len(items)} files downloaded successfully in {total_elapsed:.1f}s ({overall_speed:.1f} MB/s).")
    print(f"Local repository path: {TARGET_DIR / 'pi05_droid_jointpos'}")


if __name__ == "__main__":
    main()
