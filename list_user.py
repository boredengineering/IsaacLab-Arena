import json
for line in open("/root/.gemini/antigravity-cli/brain/4838972d-a1fb-4f7d-aec6-7a59cab29491/.system_generated/logs/transcript.jsonl"):
    try:
        data = json.loads(line)
        if data.get("type") == "USER_INPUT":
            print("USER:", data.get("content", "")[:200])
    except Exception:
        pass
