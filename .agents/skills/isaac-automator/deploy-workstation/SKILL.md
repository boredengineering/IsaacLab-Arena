---
name: deploy-workstation
description: Non-interactive multi-cloud GPU provisioning for NVIDIA Isaac Lab across AWS, GCP, Azure, and Alibaba Cloud.
---

# Deploy Workstation Skill

### Operational Invariants
1. Pass non-interactive flags: `--existing replace` or `--existing modify`. Never allow `ask` prompts in agent mode.
2. Ensure public IP lock: `--ingress-cidrs myip`.
3. Pre-baked images (`--from-image`) provision in 10–15m; bare-metal scripts (`--not-from-image`) take 45–60m.

```bash
# Example AWS deployment
./deploy --provider aws --deployment-name isaac-lab-gpu --gpu-type a10g --ingress-cidrs myip --from-image --existing replace
```
