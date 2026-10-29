---
name: session-memory
description: Architectural checkpointing, 25-character UUID logging, and INDEX.md synchronization.
---

# Session Memory Skill

- Checkpoint format: `.agents/memory/sessions/YYYYMMDD_HHMMSS_<short_uuid>.md`
- Master table sync: append row to `.agents/memory/INDEX.md`
