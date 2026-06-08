import os
import json

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
folder = "6b9ebb88-a359-4761-b630-ac6b415271e7"
msg_dir = os.path.join(brain_dir, folder, ".system_generated", "messages")
if os.path.exists(msg_dir):
    for f in os.listdir(msg_dir):
        if f.endswith(".json") and f not in ["cursor.json", "read.json"]:
            fp = os.path.join(msg_dir, f)
            with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                data = json.load(file)
                print("Keys:", data.keys())
                # print snippet of data
                print("Content preview:", str(data)[:200])
                break
