---
name: connect-workstation
description: Remote display streaming and headless shell connections (noVNC, NoMachine, NICE DCV, SSH).
---

# Connect Workstation Skill

### 3D Viewport Invariant
- **noVNC (`./novnc`)**: 2D web desktop only. Omniverse Kit renders to a Vulkan surface; blank viewports in noVNC are expected.
- **NoMachine / NICE DCV / Moonlight**: Dedicated hardware-accelerated 3D Vulkan streaming.
- **SSH (`./ssh`)**: Headless CLI control with GPU forwarding.

```bash
./connect --mode nomachine <deployment-name>
```
