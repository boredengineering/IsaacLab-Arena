"""Scale-free near-field fidelity: is a planar table planar, and does the apple's relief show?

Needs no ground truth, so it runs on the exact dataset frames training feeds. The apple's true
relief above the table is 3.4 cm at ~0.5 m, i.e. ~6.8% of the table distance -- a ratio, so it is
invariant to the global scale error that makes these teachers' absolute metres wrong.
"""
import json
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from depth_anything_3.cfg import create_object
from omegaconf import OmegaConf
from safetensors.torch import load_file
from transformers import AutoModelForDepthEstimation

P = "/workspaces/isaaclab_arena/eval_output/g1_teacher_probe"
F_PX, CX, CY = 458.12, 320.0, 240.0
IN_H, IN_W = 518, 686
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)


def prep(rgb):
    x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255.0
    x = F.interpolate(x, size=(IN_H, IN_W), mode="bilinear", align_corners=False)
    return ((x - MEAN) / STD).cuda()


def depth_da3(name, rgb):
    root = f"/models/isaaclab_arena/{name}"
    spec = json.load(open(f"{root}/config.json"))["config"]
    net = create_object(OmegaConf.create(spec))
    w = load_file(f"{root}/model.safetensors")
    rep = net.load_state_dict({k.removeprefix("model."): v for k, v in w.items()}, strict=False)
    assert not rep.unexpected_keys
    net = net.cuda().eval()
    with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
        raw = net(prep(rgb)[:, None])["depth"].float()
    return F.interpolate(raw, (480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()


def depth_dav2(rgb):
    m = AutoModelForDepthEstimation.from_pretrained(
        "depth-anything/Depth-Anything-V2-Small-hf").cuda().eval()
    with torch.no_grad():
        out = m(pixel_values=prep(rgb)).predicted_depth
    if out.dim() == 3:
        out = out[:, None]
    d = F.interpolate(out.float(), (480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()
    return 1.0 / np.clip(d, 1e-6, None)          # DA-V2 emits inverse relative depth


def analyse(label, depth, table, apple):
    """Fit a plane to the table in 3D, then measure planarity and the apple's relief."""
    yy, xx = np.mgrid[0:480, 0:640]
    def points(mask):
        z = depth[mask]
        return np.stack([(xx[mask] - CX) / F_PX * z, (yy[mask] - CY) / F_PX * z, z], 1)

    Pt = points(table)
    # least-squares plane  z = a*x + b*y + c  in camera coords
    A = np.stack([Pt[:, 0], Pt[:, 1], np.ones(len(Pt))], 1)
    coef, *_ = np.linalg.lstsq(A, Pt[:, 2], rcond=None)
    resid = A @ coef - Pt[:, 2]
    table_z = np.median(Pt[:, 2])
    planarity = float(np.sqrt((resid ** 2).mean()) / table_z)      # scale-free RMS

    Pa = points(apple)
    Aa = np.stack([Pa[:, 0], Pa[:, 1], np.ones(len(Pa))], 1)
    plane_at_apple = Aa @ coef
    relief = plane_at_apple - Pa[:, 2]                             # positive = nearer than plane
    rel_ratio = float(np.median(relief) / table_z)
    print(f"  {label:22s} table_z={table_z:6.3f}  planarity RMS={planarity*100:5.2f}% of range"
          f"   apple relief={np.median(relief)*100:+6.2f} cm = {rel_ratio*100:+5.2f}% of range"
          f"   (truth +6.8%)")
    return rel_ratio, planarity


rgb = np.asarray(Image.open(f"{P}/dataset_f0.png").convert("RGB"))
apple = np.load(f"{P}/apple_mask.npy")
grey = rgb.mean(2)
table = np.zeros_like(apple)
table[285:455, :] = True
table &= ~apple
table &= grey < 120
print(f"masks: table={table.sum()} px  apple={apple.sum()} px\n")
print("Scale-free relief test on the dataset frame (no GT needed):")
for name in ["DA3METRIC-LARGE", "DA3-BASE", "DA3MONO-LARGE"]:
    analyse(name, depth_da3(name, rgb), table, apple)
analyse("DA-V2-Small", depth_dav2(rgb), table, apple)
