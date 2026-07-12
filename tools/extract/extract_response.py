import json
msgs = []
try:
    for line in open("/root/.gemini/antigravity-cli/brain/4838972d-a1fb-4f7d-aec6-7a59cab29491/.system_generated/logs/transcript.jsonl"):
        try:
            data = json.loads(line)
        except Exception:
            continue
        if data.get("type") in ["USER_INPUT", "PLANNER_RESPONSE"]:
            msgs.append(data)

    # find the user message with "the fix doesnt work"
    for i, m in enumerate(msgs):
        if m.get("type") == "USER_INPUT" and "the fix doesnt work" in m.get("content", ""):
            # print the planner response before it
            for j in range(i-1, -1, -1):
                if msgs[j].get("type") == "PLANNER_RESPONSE":
                    print("PLANNER RESPONSE:", msgs[j].get("content", ""))
                    break
except Exception as e:
    print(e)
