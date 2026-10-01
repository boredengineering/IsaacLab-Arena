# vLLM Patches for Isaac Lab-Arena Local Inference

This directory contains targeted runtime patches for self-hosted vLLM inference containers used across Isaac Lab-Arena agentic workflows.

---

## 1. `hermes_tool_parser.py`

### Problem
When using `Qwen/Qwen2.5-Coder-32B-Instruct-AWQ` as an autonomous coding engine with vLLM, the standard `--tool-call-parser hermes` parser strictly expects `<tool_call> ... </tool_call>` XML tags.
However, Qwen 2.5 Coder variants frequently emit tool calls as:
1. `<tools> ... </tools>` XML tags
2. Direct JSON objects: `{"name": "<tool-name>", "arguments": { ... }}`

When this happens with stock vLLM:
* The parser fails to match `<tool_call>`.
* vLLM returns `tools_called=False` and puts the raw JSON string into `message.content`.
* The coding agent (Hermes Agent) receives the tool call as normal assistant text and displays `{"name": "terminal", "arguments": {"command": "..."}}` directly to the user instead of executing the tool.

### Solution
This patched `hermes_tool_parser.py` makes `Hermes2ProToolParser.extract_tool_calls` multi-format:
* Matches `<tool_call> ... </tool_call>`
* Matches `<tools> ... </tools>`
* Matches direct JSON objects containing `"name"` and `"arguments"` or `"parameters"`

### Mounting into vLLM
When launching the container, mount this file over the default vLLM parser:
```bash
-v "$(pwd)/.agents/references/plans/local-inference/vllm_patches/hermes_tool_parser.py:/usr/local/lib/python3.12/dist-packages/vllm/tool_parsers/hermes_tool_parser.py"
```
