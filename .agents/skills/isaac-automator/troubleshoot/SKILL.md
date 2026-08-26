---
name: troubleshoot
description: Automated diagnostic engine for Vulkan display issues, driver mismatches, and CIDR drift.
---

# Troubleshoot Skill

1. **Security Group IP Drift**: Run `./repair-ip <name>` if local public IP changed.
2. **Vulkan ICD Diagnostics**: Verify `/usr/share/vulkan/icd.d/nvidia_icd.json` matches NVIDIA driver version.
