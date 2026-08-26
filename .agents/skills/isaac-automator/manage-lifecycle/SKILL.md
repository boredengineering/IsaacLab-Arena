---
name: manage-lifecycle
description: Cloud instance lifecycle and cost control (stop, start, destroy --yes, cycle-vm).
---

# Manage Lifecycle Skill

### Procedures
- `./stop <name>`: Pauses GPU compute charges, retains storage and static IP.
- `./start <name>`: Resumes instance with identical IP.
- `./destroy <name> --yes`: Complete teardown, stops 100% of billing.
- `./cycle-vm <name>`: Re-creates VM before GCP 7-day Flex-start expiry while preserving data.
