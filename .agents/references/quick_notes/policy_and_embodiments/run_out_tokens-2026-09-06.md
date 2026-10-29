---
title: "Run Out of Open Router Tokens — Rollout Diagnostics"
category: "Policy Evaluation & Embodiments"
date_created: "2026-09-06"
last_updated: "2026-10-16"
status: "Incident Log & Rollout Diagnostics"
subsystem: "Policy Evaluation / OpenRouter"
tags: ["rollout-diagnostics", "openrouter", "token-exhaustion", "apple-grasp", "contact-kinematics"]
---

> **Topic / Category**: Policy Evaluation & Embodiments  
> **Date of Creation (YYYY-MM-DD)**: 2026-09-06 | **Last Updated (YYYY-MM-DD)**: 2026-10-16  
> **Status**: Incident Log & Rollout Diagnostics  
> **Subsystem**: Policy Evaluation / OpenRouter  
> **Summary**: Diagnostic rollout log capturing policy evaluation episodes when OpenRouter API tokens were exhausted, analyzing 20/20 episode trajectories for apple grasp closing behavior and gripper reopening timing.

---

# Run out of Open Router Tokens

Your hypothesis is confirmed — 20/20 episodes.

┌──────────────────────────────────────────┬─────────────────────────────────────────────┐
│                                          │                                             │
├──────────────────────────────────────────┼─────────────────────────────────────────────┤
│ hand crosses 50 % closed at              │                   ~20 % through the episode │
├──────────────────────────────────────────┼─────────────────────────────────────────────┤
│ distance to apple at that moment         │ 0.1620 m (median) — 4.8× the apple's radius │
├──────────────────────────────────────────┼─────────────────────────────────────────────┤
│ closest the hand ever gets               │                                    0.1406 m │
├──────────────────────────────────────────┼─────────────────────────────────────────────┤
│ episodes closing beyond the apple radius │                                     20 / 20 │
└──────────────────────────────────────────┴─────────────────────────────────────────────┘

Let me check whether it ever reopens, since a grasp requires open→close at contact:

  Ran 1 shell command

● Background command "Run the gripper-closure test" completed (exit code 0)

● API Error: 402 This request requires more credits, or fewer max_tokens. You requested up to 64000 tokens, but can only afford 60200. To increase, visit https://openrouter.ai/workspaces/default/keys/01b9ab7b0d852d3f2e591e5f4d0dd3258ef4e8ede0f7a1224f49f854bd0eda53 and adjust the key's total limit

✻ Worked for 1m 13s · done 1:36 AM

● Monitor event: "gripper-closure test progress"

● Monitor "gripper-closure test progress" stream ended

● API Error: 402 This request requires more credits, or fewer max_tokens. You requested up to 64000 tokens, but can only afford 60200. To increase, visit https://openrouter.ai/workspaces/default/keys/01b9ab7b0d852d3f2e591e5f4d0dd3258ef4e8ede0f7a1224f49f854bd0eda53 and adjust the key's total limit

✻ Cooked for 0s · done 1:37 AM
