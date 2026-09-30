# Local Inference Plans Index

This directory maintains architectural plans, operational runbooks, serving benchmarks, and integration guides for running self-hosted, local models (LLMs and VLMs) with Isaac Lab-Arena's agentic workflows.

---

## 1. Overview & Mission

The goal of the local inference track is to decouple Isaac Lab-Arena from external hosted model providers (e.g. OpenAI, Google Gemini, OpenRouter, NVIDIA Cloud API), providing:
- **Zero API Ingestion / Egress Costs** for continuous synthetic data generation, benchmark sweeps, and automated policy evaluations.
- **Air-Gapped & Secure Simulation Deployment** for proprietary robot embodiments, scenes, and internal assets.
- **Low-Latency Active Inference Loops** with co-located GPU inference nodes.
- **Deterministic Structured Output Guarantees** using hardware-accelerated constrained grammar decoders.

---

## 2. Plans Index

| Plan | Focus / Domain | Target Stack | Status |
| :--- | :--- | :--- | :--- |
| **[`install-multi-gpu.md`](install-multi-gpu.md)** | Physical and electrical hardware integration guide for adding the RTX 5090 to the RTX PRO 6000 Blackwell rig (PSU, 12V-2x6, PCIe bifurcation, and display cabling). | ASUS ROG X870E, Ryzen 9 9950X, RTX PRO 6000 96GB + RTX 5090 32GB, Driver 595+ | **Completed / Dual-Blackwell Verified** |
| **[`local_llm_vlm_agentic_env_gen_plan.md`](local_llm_vlm_agentic_env_gen_plan.md)** | End-to-end local inference execution plan for `agentic_environment_generation` (LLM spec synthesis, Active Inference repair, and Tier 2 local VLM visual scene critic). | Dual-Blackwell (RTX PRO 6000 96GB + RTX 5090 32GB), vLLM, Qwen2.5-72B, Qwen2.5-VL, GR00T-3B | **Active / Ready for Execution** |
| **[`experiments.md`](experiments.md)** | Live human-readable experimental journal, baseline verification records, telemetry logs, and step-by-step validation gates for local dual-GPU execution. | Dual-Blackwell, vLLM (Qwen2.5-Coder-32B / LLaMA-70B), Neo4j 5.26, Isaac Sim 6.0, GR00T-DROID | **Active Research & Execution** |

---

## 3. Scope & Shared Invariants

All local inference implementations within this directory must adhere to the following contracts:

1. **OpenAI Compatibility**:
   - Local serving engines (vLLM, SGLang, NVIDIA NIM, etc.) must expose standard `/v1/chat/completions` and `/v1/models` endpoints compatible with the core [`inference_backend.py`](../../../../isaaclab_arena/agentic_environment_generation/inference_backend.py).
2. **Strict JSON Schema Guided Decoding**:
   - Spec generation requires native schema-guided token masking (`json_schema` response format) to strictly satisfy `ArenaEnvGraphSpec` validation rules.
3. **Repository Path & Link Invariant**:
   - In accordance with the repository conventions, all cross-document references, source code anchors, and configuration files must use **repository-relative links** (never hardcoded `file:///` URIs or host paths).
4. **Host-to-Container Networking**:
   - The Arena simulation devcontainer operates under `--net=host`. All local models hosted on loopback interfaces (`127.0.0.1` or `0.0.0.0`) are addressable via `http://localhost:<port>`.

---

## 4. Planned Extensions & Future Roadmaps

- [ ] **Multi-GPU Orchestration**: Profiling memory allocation when running Isaac Sim and a 70B quantized LLM on heterogeneous vs unified multi-GPU workstations (e.g., dual RTX 4090 or single H100).
- [ ] **Cosmos-Reason Integration**: Benchmarking NVIDIA Cosmos-Reason as a specialized Tier 2 physical dynamics and spatial critic.
- [ ] **vLLM Grammar Optimization**: Benchmarking XGrammar vs Outlines for low-latency recursive schema resolution on complex factor graphs.
