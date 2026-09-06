"""Is DA3METRIC's overestimate a focal-units bug? Test every plausible convention."""
import json
import numpy as np
from PIL import Image
import torch
import torch.nn.functional as F
from depth_anything_3.cfg import create_object
from omegaconf import OmegaConf
from safetensors.torch import load_file

P = "/workspaces/isaaclab_arena/eval_output/g1_teacher_probe"
GT = "/workspaces/isaaclab_arena/eval_output/rerender/probe_set/depth/episode_000000.npz"
IN_H, IN_W = 518, 686
F_NATIVE = 15.0 / 20.955 * 640.0          # 458.12 px at 480x640
F_PROC_X = F_NATIVE * IN_W / 640.0        # 491.03 px on the fed grid
F_PROC_Y = F_NATIVE * IN_H / 480.0        # 494.38 px
MEAN = torch.tensor([0.485, 0.456, 0.406]).view(1, 3, 1, 1)
STD = torch.tensor([0.229, 0.224, 0.225]).view(1, 3, 1, 1)

root = "/models/isaaclab_arena/DA3METRIC-LARGE"
spec = json.load(open(f"{root}/config.json"))["config"]
net = create_object(OmegaConf.create(spec))
w = load_file(f"{root}/model.safetensors")
net.load_state_dict({k.removeprefix("model."): v for k, v in w.items()}, strict=True)
net = net.cuda().eval()

# the properly paired frame: rerendered RGB against its own GT depth
rgb = np.asarray(Image.open(f"{P}/rerendered_f0.png").convert("RGB"))
x = torch.from_numpy(rgb).permute(2, 0, 1)[None].float() / 255.0
x = F.interpolate(x, size=(IN_H, IN_W), mode="bilinear", align_corners=False)
x = ((x - MEAN) / STD).cuda()
with torch.no_grad(), torch.autocast("cuda", dtype=torch.bfloat16):
    raw = net(x[:, None])["depth"].float()
raw = F.interpolate(raw, (480, 640), mode="bilinear", align_corners=False)[0, 0].cpu().numpy()

gt = np.load(GT)["depth"][0].astype(np.float32)
m = np.isfinite(gt) & (gt > 0.40) & (gt < 0.60)      # the table, unambiguous surface

print(f"raw net output over the table: median={np.median(raw[m]):.4f}  GT median={np.median(gt[m]):.4f}\n")
for label, factor in [
    ("raw, no rescale",                 1.0),
    ("x f_native/300  (458.12/300)",    F_NATIVE / 300.0),
    ("x f_proc_x/300  (491.03/300)",    F_PROC_X / 300.0),
    ("x f_proc_y/300  (494.38/300)",    F_PROC_Y / 300.0),
    ("x (f_proc_x+f_proc_y)/2 /300",    (F_PROC_X + F_PROC_Y) / 2 / 300.0),
    ("/ f_native/300  (inverse)",       300.0 / F_NATIVE),
]:
    p = raw * factor
    ratio = np.median(p[m] / gt[m])
    err = np.median(np.abs(p[m] - gt[m]))
    print(f"  {label:34s} factor={factor:6.3f}  pred/gt={ratio:6.3f}x  median|err|={err*100:7.2f} cm")
