# Dual-Blackwell GPU Installation & Hardware Integration Guide

**Status:** Approved Operational Guide  
**Owner:** Isaac Lab-Arena Core Engineering  
**Target Hardware:**  
- **Primary GPU (Installed):** NVIDIA RTX PRO 6000 Blackwell Workstation Edition (96 GB GDDR7, 600W TDP, `PCI 0000:01:00.0`)  
- **Secondary GPU (To Install):** NVIDIA GeForce RTX 5090 (32 GB GDDR7 Blackwell, 600W TDP)  
- **Motherboard:** ASUS ROG CROSSHAIR X870E GLACIAL  
- **CPU:** AMD Ryzen 9 9950X 16-Core Processor (Zen 5, with integrated Radeon RDNA2 graphics)  
- **Operating System:** Ubuntu 22.04.5 LTS (Kernel `7.2.4-zabbly+`)  
- **Driver / CUDA Baseline:** NVIDIA Driver `595.91.07` | CUDA `13.2`

---

## 1. Executive Summary & Software Readiness

Because your host system is **already running NVIDIA Driver `595.91.07` on Kernel `7.2.4-zabbly+`**, both the installed **RTX PRO 6000** and the **RTX 5090** share the exact same **Blackwell architecture (`sm_120`)**.

- **No driver installation or reinstallation is needed.**
- **No CUDA toolkit or kernel module rebuild is required.**
- The Linux kernel and NVIDIA proprietary driver will detect the RTX 5090 automatically on first boot as `GPU 1`.
- Combined VRAM across both cards totals **128 GB GDDR7**.

---

## 2. Pre-Installation Hardware & Electrical Checklist

Before physically mounting the RTX 5090, verify the following three electrical and mechanical constraints:

### 2.1 Power Supply Unit (PSU) Capacity
- **RTX PRO 6000 Blackwell:** Up to **600W** TDP.
- **RTX 5090:** Up to **600W** TDP.
- **AMD Ryzen 9 9950X:** Up to **230W** (full package boost).
- **Motherboard + RAM + NVMe + Fans/Pump:** ~**100W**.
- **Peak Aggregate Draw:** Up to **~1,450W – 1,530W**.

> [!WARNING]
> **PSU Sizing Requirement:** Ensure your system is powered by a high-grade **1500W – 1600W PSU** (ATX 3.1 / PCIe 5.1 compliant).  
> If you are running on a 1000W or 1200W PSU, you **must power-cap both cards** to 400W–450W immediately upon boot (see [Section 8](#8-power-capping-guide-for-psus--1500w)) to prevent triggering Over-Current Protection (OCP) shutdowns during heavy training or simulation steps.

### 2.2 Dedicated 12V-2x6 (16-Pin) Power Cabling
- Both the RTX PRO 6000 and RTX 5090 utilize high-current **12V-2x6 / 12VHPWR (16-pin)** power interfaces.
- **Do not daisy-chain or share splitters.** Run **two completely separate native 12V-2x6 cables** directly from the PSU to each GPU.
- Ensure the 16-pin connectors are fully seated until the latch clicks with zero bending radius within 35 mm of the connector.

### 2.3 Physical Clearance & Airflow
- The RTX 5090 is typically a **3.0 to 3.5-slot thick** card.
- On the **ASUS ROG CROSSHAIR X870E GLACIAL**, verify:
  1. Installing the RTX 5090 into `PCIEX16_2` does not block bottom-edge USB, front-panel, or fan headers.
  2. There is adequate vertical clearance between the top RTX PRO 6000 and the backplate of the RTX 5090 so the top card's intake fans maintain unobstructed airflow.

---

## 3. Motherboard Slot Configuration & PCIe Bifurcation

The **ASUS ROG CROSSHAIR X870E GLACIAL** routes 24 usable PCIe 5.0 lanes directly from the Ryzen 9 9950X CPU:

| Slot Identifier | Physical Slot | Lane Allocation (Dual GPU) | Effective Bandwidth |
| :--- | :--- | :--- | :--- |
| **`PCIEX16_1` (Top)** | RTX PRO 6000 Blackwell (96 GB) | **PCIe 5.0 x8** | ~32 GB/s bidirectional |
| **`PCIEX16_2` (Bottom)** | RTX 5090 (32 GB) | **PCIe 5.0 x8** | ~32 GB/s bidirectional |

### Performance Impact of x8/x8 Bifurcation:
- When both slots are populated, the X870E motherboard automatically splits the primary 16 lanes into **Gen 5 x8 / x8**.
- Because PCIe Gen 5 doubles the per-lane throughput of Gen 4, **PCIe 5.0 x8 provides the exact same bandwidth as PCIe 4.0 x16 (~32 GB/s)**.
- Neither vLLM model weights loading nor Isaac Sim sensor tensor transfers will experience PCIe bus starvation.

---

## 4. Display Cable & Monitor Selection

### The Golden Rule: Leave the RTX 5090 Headless

```
[ Monitor Display Cable ]
           │
           ├── Option A (Recommended): Motherboard HDMI/DP (AMD Ryzen 9 9950X iGPU)
           │                           → 0 MB VRAM penalty on both NVIDIA GPUs.
           │
           └── Option B (Standard):     RTX PRO 6000 Blackwell (GPU 0)
                                       → Uses ~1.5 GB out of 96 GB VRAM.
                                       → 94.5 GB remains free for LLM inference.

[ RTX 5090 Display Ports (GPU 1) ] ──────> LEAVE COMPLETELY EMPTY
                                           → 100% of 32 GB VRAM reserved for
                                             Isaac Sim PhysX & GR00T Policy Server.
```

1. **Do not plug monitors into the RTX 5090.** Desktop environments (GNOME, Wayland/X11, Chrome/Electron apps) consume 1.5–3.0 GB of VRAM. Keeping the RTX 5090 headless preserves every megabyte of its 32 GB for Isaac Sim PhysX, Vulkan camera buffers, and the GR00T 3B policy model.
2. **Motherboard iGPU Option:** Your Ryzen 9 9950X contains an integrated AMD Radeon GPU (`amdgpu` driver loaded at PCI `0000:7c:00.0`). Plugging your monitor into the motherboard HDMI/DisplayPort offloads the desktop entirely from both NVIDIA cards.
3. **RTX PRO 6000 Option:** If plugging into a discrete GPU, connect to the **RTX PRO 6000**. Losing ~1.5 GB on a 96 GB card has zero operational impact on LLM serving.

---

## 5. Physical Installation Runbook

1. **Power Down & Discharge:**
   - Shut down the host: `sudo shutdown -h now`.
   - Switch off the PSU rocker switch and unplug the AC power cord.
   - Press the chassis power button for 10 seconds to drain motherboard capacitors.
2. **Insert the RTX 5090:**
   - Remove the PCIe expansion slot covers for the second x16 slot (`PCIEX16_2`).
   - Align the RTX 5090 with `PCIEX16_2` and press firmly until the retention latch clicks.
   - Secure the card bracket to the chassis frame with mounting screws (use a GPU anti-sag support bracket if included).
3. **Connect Power:**
   - Plug the second dedicated 12V-2x6 cable from the PSU directly into the RTX 5090.
   - Confirm the connector is inserted fully flush with no gap.
4. **Boot & BIOS Verification:**
   - Reconnect AC power and turn on the PSU.
   - Press `Del` or `F2` during boot to enter the ASUS UEFI BIOS.
   - Under **Advanced > Onboard Devices Configuration / PCIe Subsystem**, verify both `PCIEX16_1` and `PCIEX16_2` report link speeds at **Gen 5 x8**.
   - Under **Display Configuration**, verify Primary Display is set to **PEG Slot 1** (or **IGFX** if using motherboard video).
   - Save and exit (`F10`).

---

## 6. Post-Boot Verification & Health Checks

Once booted into Ubuntu 22.04, open a terminal and execute:

### Step 6.1: Verify Dual GPU Enumeration
```bash
nvidia-smi --query-gpu=index,name,pci.bus_id,memory.total,power.limit --format=csv
```

Expected output:
```csv
index, name, pci.bus_id, memory.total [MiB], power.limit [W]
0, NVIDIA RTX PRO 6000 Blackwell Workstation Edition, 00000000:01:00.0, 97887 MiB, 600.00 W
1, NVIDIA GeForce RTX 5090, 00000000:02:00.0, 32768 MiB, 600.00 W
```

### Step 6.2: Enable Persistence Mode
Ensure the NVIDIA persistence daemon keeps both cards initialized to prevent driver reload latency:
```bash
sudo nvidia-smi -pm 1
```

### Step 6.3: Check PCIe Link Negotiation
```bash
nvidia-smi --query-gpu=index,name,pcie.link.gen.current,pcie.link.width.current --format=csv
```
Confirm both cards negotiate PCIe link width at `8` and gen at `4` or `5`.

---

## 7. Workload Device Pinned Execution

Once both GPUs are active, pin tasks according to the [local inference plan](local_llm_vlm_agentic_env_gen_plan.md):

### 7.1 GPU 0 (RTX PRO 6000, 96 GB) -> Cognitive Spec Generation (vLLM)
```bash
# Serves unquantized or FP8 72B reasoning models with full 32k context
CUDA_VISIBLE_DEVICES=0 vllm serve Qwen/Qwen2.5-72B-Instruct \
  --host 0.0.0.0 \
  --port 8000 \
  --max-model-len 32768 \
  --guided-decoding-backend outlines \
  --api-key local-arena-token \
  --gpu-memory-utilization 0.85
```

### 7.2 GPU 1 (RTX 5090, 32 GB) -> GR00T Policy Server
```bash
docker run -d \
  --name gr00t-server \
  --gpus '"device=1"' \
  --network host \
  --ipc host \
  gr00t-dev:latest \
  uv run python gr00t/eval/run_gr00t_server.py \
    --model-path nvidia/GR00T-N1.6-DROID \
    --embodiment-tag OXE_DROID \
    --port 5556 \
    --device cuda:0
```

### 7.3 GPU 1 (RTX 5090, 32 GB) -> Isaac Sim / IsaacLab Simulation
Run the simulation container pinned to GPU 1:
```bash
docker exec -it --env CUDA_VISIBLE_DEVICES=1 \
  isaaclab_arena-local su $(id -un)
```

---

## 8. Power Capping Guide (For PSUs < 1500W)

If your current power supply is **1000W or 1200W**, apply persistent power caps to avoid system reboots under combined heavy load:

```bash
# Cap RTX PRO 6000 to 450W (Default is 600W)
sudo nvidia-smi -i 0 -pl 450

# Cap RTX 5090 to 400W (Default is 600W)
sudo nvidia-smi -i 1 -pl 400
```

To make these power caps persistent across reboots, create a systemd service:

```bash
sudo tee /etc/systemd/system/nvidia-power-limit.service << 'EOF'
[Unit]
Description=Set NVIDIA GPU Power Limits
After=syslog.target process-accounting.target

[Service]
Type=oneshot
ExecStart=/usr/bin/nvidia-smi -i 0 -pl 450
ExecStart=/usr/bin/nvidia-smi -i 1 -pl 400
RemainAfterExit=yes

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now nvidia-power-limit.service
```

---

## 9. Next Steps

- Review the [Local LLM/VLM Execution Plan](local_llm_vlm_agentic_env_gen_plan.md) for full pipeline testing and Active Inference verification gates.
- For issues related to devcontainer access and execution bounds, consult the [Local Inference Plans Index](README.md).
