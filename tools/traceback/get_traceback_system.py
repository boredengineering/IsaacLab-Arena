import json

for line in open("/root/.gemini/antigravity-cli/brain/4838972d-a1fb-4f7d-aec6-7a59cab29491/.system_generated/logs/transcript_full.jsonl"):
    try:
        data = json.loads(line)
        if data.get("type") == "CHECKPOINT":
            content = data.get("content", "")
            if "Traceback" in content:
                print("--- CHECKPOINT ---")
                print(content)
    except Exception:
        pass
