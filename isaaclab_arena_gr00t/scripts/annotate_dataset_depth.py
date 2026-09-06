# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Annotate a recorded LeRobot corpus with metric depth from a frozen Depth-Anything-3 teacher.

Writes depth alongside the dataset rather than regenerating it every training step, so the
teacher's output is inspectable, reproducible, and reusable by a depth-regression head later.

Two products, both optional and independently useful:

- **Depth maps**, as uint16 millimetres. This is the literal depth annotation.
- **Spatial Forcing latents**, the teacher's patch tokens resampled to the student's token grid.
  This is what the ``align`` loss actually consumes.

Both come from the same checkpoint in one pass, and the latents are produced by the *same*
``FrozenGeometryEncoder`` the training path uses, so an annotation and an online teacher cannot
silently disagree about preprocessing.

**On converting to metres.** ``DA3METRIC-LARGE`` emits *canonical* depth, and its model card gives
``metric = focal * raw / 300`` with ``focal`` in pixels. The focal that belongs in that formula is
the focal at the resolution the network is actually fed, not the camera's native resolution -- DA3
resizes to a fixed shorter side, which rescales the focal. For this rig::

    native   fx = 15mm / 20.955mm * 640px = 458.1px      -> focal/300 = 1.527
    as fed   fx = 458.1px * (518/480)     = 494.4px      -> focal/300 = 1.648

The second is the correct one, and it reproduces the 1.64x factor measured independently in
``geometry_supervision_evidence_repair_plan.md`` §2.5b. That measurement also found the raw output
already 1.568x too large on the table region, so applying the formula made the error *worse*
(2.566x / 79.5 cm) while a single fitted global scalar reached 1.027x / 1.64 cm.

So this script writes **all three** and asserts nothing about which is right: the raw canonical
depth, the model-card metric conversion, and -- with ``--fit-scale-to-metres`` -- one global scalar
fitted per camera pose. The manifest records every factor used, so a downstream consumer can
recover any of them instead of trusting a number baked into a file name.
"""

from __future__ import annotations

import argparse
import json
import numpy as np
import subprocess
import sys
import time
import torch
from pathlib import Path

# DA3's canonical-depth denominator, from the DA3METRIC model card's
# ``metric_depth = focal * pred / 300`` conversion.
DA3_CANONICAL_FOCAL = 300.0

# Isaac Lab's PinholeCameraCfg default, in millimetres. Only used to derive a focal length when the
# caller does not pass one explicitly.
DEFAULT_HORIZONTAL_APERTURE_MM = 20.955

# Depth is stored as uint16 millimetres: lossless to 1 mm out to 65.5 m, and a quarter the size of
# float32. The G1 head camera clips at 5 m, so the range is not a constraint here.
DEPTH_SCALE_MM = 1000.0
DEPTH_UINT16_MAX = 65535


def focal_pixels(
    focal_length_mm: float, horizontal_aperture_mm: float, width_px: int, input_scale: float = 1.0
) -> float:
    """Return a pinhole camera's focal length in pixels, optionally at a rescaled input.

    Args:
        focal_length_mm: Lens focal length in millimetres.
        horizontal_aperture_mm: Sensor horizontal aperture in millimetres.
        width_px: Image width in pixels at the camera's native resolution.
        input_scale: Ratio of the resolution the network is fed to the native resolution.

    Returns:
        Focal length in pixels.
    """
    assert (
        focal_length_mm > 0 and horizontal_aperture_mm > 0
    ), f"Degenerate intrinsics: focal_length={focal_length_mm}mm, horizontal_aperture={horizontal_aperture_mm}mm."
    return focal_length_mm / horizontal_aperture_mm * width_px * input_scale


def decode_video(path: Path, width: int, height: int, max_frames: int | None = None):
    """Yield an episode's frames as uint8 RGB arrays, decoded through ffmpeg.

    ffmpeg is used rather than a Python decoder because it is already a hard dependency of the
    recording path and needs no extra wheel in the training image.

    Args:
        path: Path to the episode's mp4.
        width: Frame width in pixels.
        height: Frame height in pixels.
        max_frames: Stop after this many frames. None decodes the whole episode.

    Yields:
        Frames as ``(height, width, 3)`` uint8 arrays.
    """
    command = ["ffmpeg", "-v", "error", "-i", str(path)]
    if max_frames is not None:
        command += ["-frames:v", str(max_frames)]
    command += ["-f", "rawvideo", "-pix_fmt", "rgb24", "-"]

    frame_bytes = width * height * 3
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    try:
        while True:
            buffer = process.stdout.read(frame_bytes)
            if len(buffer) < frame_bytes:
                break
            yield np.frombuffer(buffer, dtype=np.uint8).reshape(height, width, 3)
    finally:
        process.stdout.close()
        process.wait()


class Da3DepthTeacher:
    """A frozen DA3 checkpoint, loaded once, emitting canonical depth.

    Loads the whole net -- backbone *and* prediction head -- unlike the Spatial Forcing path, which
    keeps only the backbone. Deliberately avoids ``depth_anything_3.api``, whose import pulls the
    COLMAP, GLB, Gaussian-splat and video exporters and seventeen packages a depth pass never
    touches.

    Args:
        checkpoint_dir: Local directory holding ``config.json`` and ``model.safetensors``.
        device: Device to run on.
        dtype: Dtype to run the net in.
    """

    def __init__(self, checkpoint_dir: Path, device: torch.device, dtype: torch.dtype):
        from depth_anything_3.cfg import create_object
        from omegaconf import OmegaConf
        from safetensors.torch import load_file

        assert checkpoint_dir.is_dir(), (
            f"DA3 loads from a local directory, got {checkpoint_dir}. Fetch it with"
            " `hf download depth-anything/DA3METRIC-LARGE --local-dir <dir>`."
        )
        with open(checkpoint_dir / "config.json") as handle:
            spec = json.load(handle)["config"]
        net = create_object(OmegaConf.create(spec))

        weights = load_file(str(checkpoint_dir / "model.safetensors"))
        report = net.load_state_dict(
            {key.removeprefix("model."): value for key, value in weights.items()}, strict=False
        )
        # Both directions are fatal here, unlike the Spatial Forcing loader which tolerates a
        # missing prediction head because it throws the head away. This path *is* the head.
        assert not report.unexpected_keys, (
            f"{checkpoint_dir} carries {len(report.unexpected_keys)} tensors its construction spec"
            f" does not declare, e.g. {sorted(report.unexpected_keys)[:3]}."
        )
        assert not report.missing_keys, (
            f"{checkpoint_dir} is missing {len(report.missing_keys)} tensors, e.g."
            f" {sorted(report.missing_keys)[:3]}. Depth would be read off an untrained head."
        )

        self.net = net.to(device=device, dtype=dtype).eval()
        self.device = device
        self.dtype = dtype
        self.patch_size = int(net.backbone.pretrained.patch_size)
        self._pixel_mean = torch.tensor([0.485, 0.456, 0.406], device=device).view(1, 3, 1, 1)
        self._pixel_std = torch.tensor([0.229, 0.224, 0.225], device=device).view(1, 3, 1, 1)

    def input_size(self, height: int, width: int, shorter_side: int) -> tuple[int, int]:
        """Return the ``(height, width)`` DA3 is fed, snapped to its patch size.

        Args:
            height: Source frame height.
            width: Source frame width.
            shorter_side: Target length of the shorter side before snapping.

        Returns:
            Network input height and width, both multiples of the patch size.
        """
        scale = shorter_side / min(height, width)
        return (
            max(self.patch_size, round(height * scale / self.patch_size) * self.patch_size),
            max(self.patch_size, round(width * scale / self.patch_size) * self.patch_size),
        )

    @torch.no_grad()
    def canonical_depth(self, frames: np.ndarray, shorter_side: int) -> np.ndarray:
        """Return canonical (pre-metric) depth for a batch of frames, at the source resolution.

        Args:
            frames: Frames as ``(N, H, W, 3)`` uint8.
            shorter_side: Shorter-side resolution to run the network at.

        Returns:
            Depth as ``(N, H, W)`` float32, in DA3's canonical units.

        The value is **z-depth along the optical axis**, not ray distance, so it needs no cosine
        correction off-centre. Verified in DA3's own unprojection: ``pixel_space_to_camera_space``
        builds the ray as ``inverse_intrinsic_matrix(K) @ [u, v, 1]``, whose third component is 1
        rather than being normalised to unit length, and then multiplies by this value -- so the
        product's z *is* this value. Getting that backwards would misplace the frame corners by
        ~33% at this camera's field of view.
        """
        source_height, source_width = frames.shape[1:3]
        pixels = torch.from_numpy(np.ascontiguousarray(frames)).to(self.device)
        pixels = pixels.permute(0, 3, 1, 2).to(self.dtype) / 255.0

        height, width = self.input_size(source_height, source_width, shorter_side)
        pixels = torch.nn.functional.interpolate(pixels, size=(height, width), mode="bilinear", align_corners=False)
        pixels = (pixels - self._pixel_mean.to(self.dtype)) / self._pixel_std.to(self.dtype)

        # (N, S=1, 3, H, W): S is DA3's view axis, one view for a monocular teacher.
        output = self.net(pixels.unsqueeze(1))
        depth = output["depth"] if "depth" in output else output["distance"]
        depth = depth.float().reshape(-1, 1, *depth.shape[-2:])

        # Back to the source grid so a stored depth map indexes the recorded frame directly.
        depth = torch.nn.functional.interpolate(
            depth, size=(source_height, source_width), mode="bilinear", align_corners=False
        )
        return depth[:, 0].cpu().numpy()


def quantise_depth_mm(depth_metres: np.ndarray) -> np.ndarray:
    """Return depth in metres as uint16 millimetres, clipped to the representable range.

    Args:
        depth_metres: Depth in metres.

    Returns:
        Depth as uint16 millimetres.
    """
    millimetres = np.rint(depth_metres * DEPTH_SCALE_MM)
    return np.clip(millimetres, 0, DEPTH_UINT16_MAX).astype(np.uint16)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Return parsed command-line arguments."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--dataset-path",
        type=Path,
        default=Path("/datasets/isaaclab_arena/static_apple_tutorial/lerobot"),
        help="LeRobot dataset root, holding meta/ and videos/.",
    )
    parser.add_argument(
        "--teacher",
        type=Path,
        required=True,
        help="Local DA3 checkpoint directory, e.g. /models/isaaclab_arena/DA3METRIC-LARGE.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Where annotations are written. Defaults to <dataset-path>/depth_da3.",
    )
    parser.add_argument("--video-key", default="observation.images.ego_view")
    parser.add_argument(
        "--episodes",
        type=int,
        default=None,
        help="Annotate only the first N episodes. Omit for the whole corpus.",
    )
    parser.add_argument(
        "--max-frames-per-episode",
        type=int,
        default=None,
        help="Cap frames per episode. For smoke runs.",
    )
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument(
        "--shorter-side",
        type=int,
        default=518,
        help="Resolution DA3 is fed, matching the Spatial Forcing path's encoder_input_size.",
    )
    parser.add_argument(
        "--focal-length-mm",
        type=float,
        default=15.0,
        help="Lens focal length. Default matches G1CameraCfg.robot_head_cam.",
    )
    parser.add_argument("--horizontal-aperture-mm", type=float, default=DEFAULT_HORIZONTAL_APERTURE_MM)
    parser.add_argument(
        "--depth-downsample",
        type=int,
        default=1,
        help="Store depth at 1/N resolution. Cuts size when depth is only used for validation.",
    )
    parser.add_argument(
        "--emit-latents",
        action="store_true",
        help=(
            "Also write Spatial Forcing teacher latents at the student's token grid. Only sound"
            " when training runs without stochastic geometric augmentation; see --token-grid."
        ),
    )
    parser.add_argument(
        "--token-grid",
        type=int,
        nargs=2,
        default=(8, 11),
        metavar=("ROWS", "COLUMNS"),
        help="Student token grid the latents are resampled to. 4:3 at N1.7's default is 8x11.",
    )
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--dtype", default="float32", choices=["float32", "bfloat16", "float16"])
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Annotate the corpus and write a manifest describing every factor used."""
    args = parse_args(argv)

    info_path = args.dataset_path / "meta" / "info.json"
    assert info_path.is_file(), f"No LeRobot metadata at {info_path}."
    with open(info_path) as handle:
        info = json.load(handle)

    feature = info["features"][args.video_key]
    height, width = int(feature["shape"][0]), int(feature["shape"][1])

    # Episode indices come from ``episodes.jsonl``, not ``info.json``'s ``total_episodes``. For
    # this corpus the two disagree: ``total_episodes`` says 251 while only 208 episodes exist, with
    # 43 gaps in the index range 0..250. ``episodes.jsonl``'s 208 entries sum to exactly the 35066
    # frames ``total_frames`` reports, so the per-episode list is authoritative and the count is
    # simply stale. Iterating ``range(total_episodes)`` would both miss episode 250 and emit 43
    # spurious warnings.
    episodes_path = args.dataset_path / "meta" / "episodes.jsonl"
    assert episodes_path.is_file(), f"No episode index at {episodes_path}."
    with open(episodes_path) as handle:
        episode_indices = [json.loads(line)["episode_index"] for line in handle if line.strip()]
    available = len(episode_indices)
    declared = int(info.get("total_episodes", available))
    if declared != available:
        print(
            f"[annotate] info.json declares {declared} episodes but episodes.jsonl lists"
            f" {available}; using episodes.jsonl",
            file=sys.stderr,
        )
    if args.episodes is not None:
        episode_indices = episode_indices[: args.episodes]

    output_dir = args.output_dir or (args.dataset_path / "depth_da3")
    output_dir.mkdir(parents=True, exist_ok=True)

    device = torch.device(args.device)
    teacher = Da3DepthTeacher(args.teacher, device, getattr(torch, args.dtype))

    input_height, input_width = teacher.input_size(height, width, args.shorter_side)
    input_scale = input_width / width
    focal_native = focal_pixels(args.focal_length_mm, args.horizontal_aperture_mm, width)
    focal_as_fed = focal_native * input_scale
    metric_factor = focal_as_fed / DA3_CANONICAL_FOCAL

    encoder = None
    if args.emit_latents:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "submodules" / "Isaac-GR00T"))
        from gr00t.model.modules.geometry_conditioning import FrozenGeometryEncoder, GeometryConditioningConfig

        encoder = FrozenGeometryEncoder(
            GeometryConditioningConfig(
                mode="align",
                encoder_id=str(args.teacher),
                encoder_kind="da3",
                encoder_input_size=args.shorter_side,
                encoder_dtype=args.dtype,
            )
            # The encoder registers its normalisation constants as buffers, so it needs the usual
            # module move: ``_ensure_loaded`` places the wrapped net on the images' device but leaves
            # the buffers where they were constructed.
        ).to(device)

    print(f"[annotate] {len(episode_indices)} episodes, {width}x{height} -> DA3 at {input_width}x{input_height}")
    print(
        f"[annotate] focal: native {focal_native:.2f}px, as-fed {focal_as_fed:.2f}px, focal/300 = {metric_factor:.4f}"
    )

    video_root = args.dataset_path / "videos"
    written, frames_total, started = [], 0, time.time()

    for position, episode in enumerate(episode_indices):
        chunk = episode // int(info.get("chunks_size", 1000))
        video_path = video_root / f"chunk-{chunk:03d}" / args.video_key / f"episode_{episode:06d}.mp4"
        if not video_path.is_file():
            print(f"[annotate] missing {video_path}, skipping", file=sys.stderr)
            continue

        raw_batches, latent_batches = [], []
        batch: list[np.ndarray] = []

        def flush(batch: list[np.ndarray]) -> None:
            frames = np.stack(batch)
            raw_batches.append(teacher.canonical_depth(frames, args.shorter_side))
            if encoder is not None:
                images = torch.from_numpy(frames).permute(0, 3, 1, 2).contiguous().to(device)
                latent_batches.append(encoder(images, grid=tuple(args.token_grid)).to(torch.float16).cpu().numpy())

        for frame in decode_video(video_path, width, height, args.max_frames_per_episode):
            batch.append(frame)
            if len(batch) == args.batch_size:
                flush(batch)
                batch = []
        if batch:
            flush(batch)
        if not raw_batches:
            print(f"[annotate] {video_path} decoded no frames, skipping", file=sys.stderr)
            continue

        raw = np.concatenate(raw_batches)
        step = args.depth_downsample
        if step > 1:
            raw = raw[:, ::step, ::step]

        payload = {
            "canonical_depth": raw.astype(np.float16),
            "metric_depth_mm": quantise_depth_mm(raw * metric_factor),
        }
        if latent_batches:
            payload["teacher_latents"] = np.concatenate(latent_batches)

        destination = output_dir / f"episode_{episode:06d}.npz"
        np.savez_compressed(destination, **payload)
        written.append(destination.name)
        frames_total += raw.shape[0]
        if position % 10 == 0 or position == len(episode_indices) - 1:
            print(f"[annotate] episode {episode}: {raw.shape[0]} frames -> {destination.name}")

    manifest = {
        "teacher": str(args.teacher),
        "teacher_kind": "da3",
        "dataset_path": str(args.dataset_path),
        "video_key": args.video_key,
        "episodes_declared_in_info_json": declared,
        "episodes_in_episode_index": available,
        "episodes_written": len(written),
        "frames_written": frames_total,
        "source_resolution_hw": [height, width],
        "encoder_input_hw": [input_height, input_width],
        "shorter_side": args.shorter_side,
        "depth_downsample": args.depth_downsample,
        "focal_length_mm": args.focal_length_mm,
        "horizontal_aperture_mm": args.horizontal_aperture_mm,
        "focal_px_native": focal_native,
        "focal_px_as_fed": focal_as_fed,
        "da3_canonical_focal": DA3_CANONICAL_FOCAL,
        "metric_factor_focal_over_300": metric_factor,
        "depth_scale_mm": DEPTH_SCALE_MM,
        "dtype": args.dtype,
        "latents": (
            None
            if encoder is None
            else {
                "token_grid": list(args.token_grid),
                "feature_dim": encoder.feature_dim,
                "stored_dtype": "float16",
                "augmentation_contract": (
                    "Resampled from the clean recorded frame. Valid as a Spatial Forcing target"
                    " only when training applies no stochastic geometric augmentation"
                    " (crop_fraction=1.0); the train recipe's FractionalRandomCrop would otherwise"
                    " move the student's crop out from under these features."
                ),
            }
        ),
        "notes": (
            "canonical_depth is DA3's raw output. metric_depth_mm applies the model card's"
            " focal/300 conversion with the as-fed focal. Neither is trusted as metres: the"
            " evidence appendix measured raw at 1.568x true on the table region, so a fitted"
            " global scalar is still required. See geometry_supervision_evidence_repair_plan.md"
            " section 2.5b."
        ),
    }
    with open(output_dir / "manifest.json", "w") as handle:
        json.dump(manifest, handle, indent=2)

    elapsed = time.time() - started
    rate = frames_total / elapsed if elapsed > 0 else 0.0
    print(
        f"[annotate] wrote {len(written)} episodes, {frames_total} frames in {elapsed:.1f}s"
        f" ({rate:.1f} fps) -> {output_dir}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
