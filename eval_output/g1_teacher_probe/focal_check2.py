# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Distinguish 'divide by f/300' from 'resize so the fed focal IS 300'."""

import json
import numpy as np
import torch
import torch.nn.functional as F

from depth_anything_3.cfg import create_object
from omegaconf import OmegaConf
from PIL import Image
from safetensors.torch import load_file

P = "/workspaces/isaaclab_arena/eval_output/g1_teacher_probe"
GT = "/workspaces/isaaclab_arena/eval_output/rerender/probe_set/depth/episode_000000.npz"
F_NATIVE = 15.0 / 20.955 * 640.0
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

root = "/models/isaaclab_arena/DA3METRIC-LARGE"
spec = json.load(open(f"{root}/config.json"))["config"]
net = create_object(OmegaConf.create(spec))
w = load_file(f"{root}/model.safetensors")
net.load_state_dict({k.removeprefix("model."): v for k, v in w.items()}, strict=True)
net = net.cuda().eval()
rgb = np.asarray(Image.open(f"{P}/rerendered_f0.png").convert("RGB"))
gt = np.load(GT)["depth"][0].astype(np.float32)
m = np.isfinite(gt) & (gt > 0.40) & (gt < 0.60)


def run(in_h, in_w):
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255.0
    x = F.interpolate(x, size=(in_h, in_w), mode="bilinear", align_corners=False)
    x = ((x - MEAN) / STD).cuda()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        raw = net(x[:, None])["depth"].float()
    return F.interpolate(raw, (480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()


print(f"GT table median = {np.median(gt[m]):.4f} m   f_native = {F_NATIVE:.2f} px\n")
# each candidate input size, with the effective focal it implies
for in_h, in_w in [(518, 686), (308, 420), (322, 434), (294, 392), (476, 630)]:
    f_eff = F_NATIVE * in_w / 640.0
    raw = run(in_h, in_w)
    r_raw = np.median(raw[m] / gt[m])
    # DA3's formula with the focal of the FED image
    r_doc = np.median((raw * f_eff / 300.0)[m] / gt[m])
    e_raw = np.median(np.abs(raw - gt)[m])
    print(
        f"  fed {in_h}x{in_w:4d}  f_eff={f_eff:6.2f}  raw pred/gt={r_raw:6.3f}x "
        f"(|err|={e_raw*100:6.2f} cm)   with xf_eff/300: {r_doc:6.3f}x"
    )
