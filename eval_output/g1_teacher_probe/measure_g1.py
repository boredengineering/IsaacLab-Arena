# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Measure DA3METRIC-LARGE's absolute metric depth error against Isaac Sim ground truth."""

import json
import numpy as np
import torch
import torch.nn.functional as F

from depth_anything_3.cfg import create_object
from omegaconf import OmegaConf
from PIL import Image
from safetensors.torch import load_file

ROOT = "/models/isaaclab_arena/DA3METRIC-LARGE"
PROBE = "/workspaces/isaaclab_arena/eval_output/g1_teacher_probe"
GT_NPZ = "/workspaces/isaaclab_arena/eval_output/rerender/probe_set/depth/episode_000000.npz"
FOCAL_PX_NATIVE = 15.0 / 20.955 * 640.0  # focal_length / horizontal_aperture * width
IN_H, IN_W = 518, 686  # multiples of 14, near-preserving 480x640
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def load_net():
    spec = json.load(open(f"{ROOT}/config.json"))["config"]
    net = create_object(OmegaConf.create(spec))
    w = load_file(f"{ROOT}/model.safetensors")
    net.load_state_dict({k.removeprefix("model."): v for k, v in w.items()}, strict=True)
    return net.cuda().eval()


def metric_depth(net, rgb_uint8):
    """Return DA3's metric depth in metres, at native 480x640."""
    x = torch.from_numpy(rgb_uint8).permute(2, 0, 1)[None].float() / 255.0
    x = F.interpolate(x, size=(IN_H, IN_W), mode="bilinear", align_corners=False)
    x = ((x - MEAN) / STD).cuda()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        raw = net(x[:, None])["depth"].float()  # (1,1,IN_H,IN_W), net units
    # DA3's metric convention: depth_m = focal_px * net_output / 300, focal at the fed resolution.
    focal_fed = FOCAL_PX_NATIVE * IN_W / 640.0
    d = raw * focal_fed / 300.0
    return F.interpolate(d, size=(480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()


def stats(pred, gt, mask, label):
    e = (pred - gt)[mask]
    print(
        f"  {label:26s} n={mask.sum():7d}  median|e|={np.median(np.abs(e)) * 100:7.2f} cm"
        f"  mean e={e.mean() * 100:+7.2f} cm  p90|e|={np.percentile(np.abs(e), 90) * 100:7.2f} cm"
    )
    return float(np.median(np.abs(e)))


net = load_net()
gt = np.load(GT_NPZ)["depth"][0].astype(np.float32)  # all 60 frames are identical
rerender = np.asarray(Image.open(f"{PROBE}/rerendered_f0.png").convert("RGB"))
dataset = np.asarray(Image.open(f"{PROBE}/dataset_f0.png").convert("RGB"))

valid = np.isfinite(gt) & (gt > 0.15) & (gt < 5.0)
table = valid & (gt > 0.35) & (gt < 0.85)  # tabletop band, excludes arms and far room

print(f"focal(native)={FOCAL_PX_NATIVE:.2f}px  GT range={gt.min():.3f}-{gt.max():.3f} m")
print("\nA. PAIRED  DA3 on the rerendered RGB vs its own GT depth")
pred_rr = metric_depth(net, rerender)
stats(pred_rr, gt, valid, "whole frame")
stats(pred_rr, gt, table, "tabletop band 0.35-0.85m")

print("\nB. UNPAIRED  DA3 on the dataset RGB (what training feeds) vs the same GT")
pred_ds = metric_depth(net, dataset)
stats(pred_ds, gt, valid, "whole frame")
stats(pred_ds, gt, table, "tabletop band 0.35-0.85m")

print("\nC. Material gap: rerendered vs dataset prediction, same geometry")
d = np.abs(pred_rr - pred_ds)[valid]
print(f"  median |pred_rr - pred_ds| = {np.median(d) * 100:.2f} cm   p90 = {np.percentile(d, 90) * 100:.2f} cm")

np.save(f"{PROBE}/pred_rerendered.npy", pred_rr)
np.save(f"{PROBE}/pred_dataset.npy", pred_ds)
