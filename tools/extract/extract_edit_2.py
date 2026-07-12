import json
for line in open("/root/.gemini/antigravity-cli/brain/4838972d-a1fb-4f7d-aec6-7a59cab29491/.system_generated/logs/transcript.jsonl"):
    data = json.loads(line)
    if data.get("type") == "PLANNER_RESPONSE":
        calls = data.get("tool_calls", [])
        for c in calls:
            if c.get("name") == "run_command":
                cmd = c.get("args", {}).get("CommandLine", "")
                if "processor_config.json" in cmd:
                    print(cmd)
