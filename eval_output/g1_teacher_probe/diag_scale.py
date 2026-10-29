# Copyright (c) 2026, The Isaac Lab Arena Project Developers (https://github.com/isaac-sim/IsaacLab-Arena/blob/main/CONTRIBUTORS.md).
# All rights reserved.
#
# SPDX-License-Identifier: Apache-2.0

"""Separate an absolute-scale error from a genuine failure to see relative geometry."""

import numpy as np

gt = np.load("/workspaces/IsaacLab-Arena/eval_output/rerender/probe_set/depth/episode_000000.npz")["depth"][0].astype(
    np.float32
)
valid = np.isfinite(gt) & (gt > 0.15) & (gt < 5.0)
table = valid & (gt > 0.35) & (gt < 0.85)

for name in ["rerendered", "dataset"]:
    p = np.load(f"/workspaces/IsaacLab-Arena/eval_output/g1_teacher_probe/pred_{name}.npy")
    print(f"\n{name.upper()} RGB")
    for label, m in [("whole frame", valid), ("tabletop band", table)]:
        P, G = p[m], gt[m]
        raw = np.median(np.abs(P - G))
        ratio = np.median(P / G)
        s = float((P * G).sum() / (P * P).sum())  # least-squares scale, pred->gt
        sc = np.median(np.abs(s * P - G))
        A = np.stack([P, np.ones_like(P)], 1)  # scale + shift
        coef, *_ = np.linalg.lstsq(A, G, rcond=None)
        ss = np.median(np.abs(A @ coef - G))
        r = np.corrcoef(P, G)[0, 1]
        print(
            f"  {label:14s} raw={raw*100:6.2f}cm  med(pred/gt)={ratio:5.2f}x"
            f"  after scale={sc*100:5.2f}cm (s={s:.3f})"
            f"  after scale+shift={ss*100:5.2f}cm  pearson r={r:+.4f}"
        )
