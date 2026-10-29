# Grounded Task Specification: Task Name

## 1. Scene Geometry & Metric Ground Planes
- **Ground Plane**: `default_ground_plane` ($z = 0.0\text{ m}$)
- **Workspace Bounds**: $x \in [-1.0, 1.0]$, $y \in [-1.0, 1.0]$, $z \in [0.0, 2.0]$
- **Table / Surface Height**: $z_{\text{table}} = 0.75\text{ m}$

## 2. Embodiment & Kinematic Reachability
- **Embodiment**: Unitree G1 / DROID Franka
- **Control Interface**: WBC Pink (`--num_envs 1`) / Joint WBC
- **Reachability Envelope ($\mathcal{W}_{\text{reach}}$)**: Max reach $0.65\text{ m}$ from base origin.

## 3. Sensor Modalities & Port Mapping
- **Camera Extrinsics**: `ego_view` RGB-D (1280x720, 30fps)
- **Policy Server Port**: ZeroMQ `tcp://127.0.0.1:5556`
