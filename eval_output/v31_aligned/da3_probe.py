#!/usr/bin/env python3
"""DA3 Metric Depth Probe: Measure perceived metric depth and pitch between demo and sim."""

import json
from pathlib import Path
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from depth_anything_3.cfg import create_object
from omegaconf import OmegaConf
from safetensors.torch import load_file

ROOT = "/models/isaaclab_arena/DA3METRIC-LARGE"
FOCAL_PX_NATIVE = 15.0 / 20.955 * 640.0  # focal_length / horizontal_aperture * width (~458.12 px)
IN_H, IN_W = 518, 686                    # multiples of 14 near 480x640
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
        raw = net(x[:, None])["depth"].float()
    focal_fed = FOCAL_PX_NATIVE * IN_W / 640.0
    d = raw * focal_fed / 300.0
    return F.interpolate(d, size=(480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()


def find_apple_mask(rgb):
    """Segment red apple using color threshold in RGB."""
    r = rgb[:, :, 0].astype(float)
    g = rgb[:, :, 1].astype(float)
    b = rgb[:, :, 2].astype(float)
    # Red dominance
    redness = r - np.maximum(g, b); red_mask = redness > 50
    # Constrain to plausible tabletop region: rows 150 to 450
    mask = np.zeros_like(red_mask)
    mask[150:450, 50:590] = red_mask[150:450, 50:590]
    return mask


def fit_plane_ransac(points, n_iter=200, dist_thresh=0.005):
    """Fit a 3D plane ax + by + cz + d = 0 using RANSAC."""
    best_inliers = 0
    best_plane = None
    n = len(points)
    if n < 3:
        return None, 0
    for _ in range(n_iter):
        idx = np.random.choice(n, 3, replace=False)
        p1, p2, p3 = points[idx]
        v1 = p2 - p1
        v2 = p3 - p1
        normal = np.cross(v1, v2)
        norm = np.linalg.norm(normal)
        if norm < 1e-6:
            continue
        normal /= norm
        d = -np.dot(normal, p1)
        dists = np.abs(np.dot(points, normal) + d)
        inliers = np.sum(dists < dist_thresh)
        if inliers > best_inliers:
            best_inliers = inliers
            best_plane = (normal, d)
    return best_plane, best_inliers


def analyze_frame(net, img_path, label):
    img = np.asarray(Image.open(img_path).convert("RGB"))
    depth = metric_depth(net, img)

    apple_mask = find_apple_mask(img)
    apple_pixels = int(apple_mask.sum())

    if apple_pixels > 0:
        apple_depths = depth[apple_mask]
        apple_z_median = float(np.median(apple_depths))
        apple_z_mean = float(np.mean(apple_depths))
        # Center of mass in pixel coords
        ys, xs = np.where(apple_mask)
        cy, cx = float(np.mean(ys)), float(np.mean(xs))
        # Apparent bounding box
        bbox_w = float(xs.max() - xs.min() + 1)
        bbox_h = float(ys.max() - ys.min() + 1)
        equiv_diam = float(2 * np.sqrt(apple_pixels / np.pi))

        # 3D position in camera optical frame (X right, Y down, Z forward)
        cam_x = (cx - 320.0) * apple_z_median / FOCAL_PX_NATIVE
        cam_y = (cy - 240.0) * apple_z_median / FOCAL_PX_NATIVE
        cam_z = apple_z_median
        cam_dist = float(np.sqrt(cam_x**2 + cam_y**2 + cam_z**2))
    else:
        apple_z_median = None
        apple_z_mean = None
        cx, cy = None, None
        bbox_w, bbox_h, equiv_diam = None, None, None
        cam_x, cam_y, cam_z, cam_dist = None, None, None, None

    # Table plane analysis: sample points from middle region of the tabletop
    table_mask = np.zeros((480, 640), dtype=bool)
    table_mask[280:440, 100:540] = True
    table_mask &= ~apple_mask
    t_ys, t_xs = np.where(table_mask)
    t_zs = depth[table_mask]

    # Unproject table points
    t_X = (t_xs - 320.0) * t_zs / FOCAL_PX_NATIVE
    t_Y = (t_ys - 240.0) * t_zs / FOCAL_PX_NATIVE
    t_Z = t_zs
    pts = np.stack([t_X, t_Y, t_Z], axis=1)

    plane, inliers = fit_plane_ransac(pts)
    if plane is not None:
        normal, d_val = plane
        # Camera Y is down, table normal points up in world, so normal_Y < 0
        if normal[1] > 0:
            normal = -normal
            d_val = -d_val
        # Pitch down from horizontal: pitch = arctan2(-normal[2], -normal[1])
        pitch_deg = float(np.degrees(np.arctan2(-normal[2], -normal[1])))
    else:
        normal = None
        pitch_deg = None

    return {
        "label": label,
        "apple_pixels": apple_pixels,
        "apple_center_px": [round(cx, 1), round(cy, 1)] if cx is not None else None,
        "bbox_wh_px": [round(bbox_w, 1), round(bbox_h, 1)] if bbox_w is not None else None,
        "equiv_diameter_px": round(equiv_diam, 2) if equiv_diam is not None else None,
        "apple_z_median_m": round(apple_z_median, 4) if apple_z_median is not None else None,
        "apple_z_mean_m": round(apple_z_mean, 4) if apple_z_mean is not None else None,
        "camera_frame_xyz_m": [round(cam_x, 4), round(cam_y, 4), round(cam_z, 4)] if cam_x is not None else None,
        "camera_dist_3d_m": round(cam_dist, 4) if cam_dist is not None else None,
        "table_normal_cam": [round(float(v), 4) for v in normal] if normal is not None else None,
        "camera_pitch_deg": round(pitch_deg, 2) if pitch_deg is not None else None,
    }


def main():
    net = load_net()
    demo_path = Path("/workspaces/isaaclab_arena/eval_output/v31_aligned/demo_0_head_cam.png")
    sim_path = Path("/workspaces/isaaclab_arena/eval_output/v31_aligned/v31_head_cam.png")

    print(f"[DA3 Probe] Analyzing Demonstration: {demo_path}")
    demo_res = analyze_frame(net, demo_path, "Teleop Demonstration (demo_0)")
    print(f"[DA3 Probe] Analyzing Simulation: {sim_path}")
    sim_res = analyze_frame(net, sim_path, "Simulation v31 (v31_head_cam)")

    out = {
        "demonstration": demo_res,
        "simulation": sim_res,
        "comparison": {},
    }

    if demo_res["apple_z_median_m"] and sim_res["apple_z_median_m"]:
        dz = sim_res["apple_z_median_m"] - demo_res["apple_z_median_m"]
        ddist = sim_res["camera_dist_3d_m"] - demo_res["camera_dist_3d_m"]
        dpitch = sim_res["camera_pitch_deg"] - demo_res["camera_pitch_deg"]
        dpixels = sim_res["apple_pixels"] - demo_res["apple_pixels"]
        out["comparison"] = {
            "delta_depth_z_m": round(dz, 4),
            "delta_dist_3d_m": round(ddist, 4),
            "delta_pitch_deg": round(dpitch, 2),
            "delta_apple_pixels": dpixels,
            "pixel_size_ratio": round(sim_res["apple_pixels"] / max(1, demo_res["apple_pixels"]), 3),
        }

    out_file = Path("/workspaces/isaaclab_arena/eval_output/v31_aligned/da3_probe_report.json")
    with open(out_file, "w") as f:
        json.dump(out, f, indent=2)
    print(f"[DA3 Probe] Saved report to: {out_file}")
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
