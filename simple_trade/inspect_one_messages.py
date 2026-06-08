import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
folder = "6b9ebb88-a359-4761-b630-ac6b415271e7"
msg_dir = os.path.join(brain_dir, folder, ".system_generated", "messages")

if os.path.exists(msg_dir):
    files = sorted(os.listdir(msg_dir), key=lambda x: os.path.getmtime(os.path.join(msg_dir, x)))
    print(f"=== Messages in {folder} ===")
    for f in files:
        if f.endswith(".json") and f not in ["cursor.json", "read.json"]:
            fp = os.path.join(msg_dir, f)
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                    data = json.load(file)
                    # messages might have different formats
                    # Let's inspect the key fields
                    sender = data.get("sender", "")
                    content = data.get("content", "")
                    if content:
                        clean_content = content.replace("<USER_REQUEST>\n", "").replace("\n</USER_REQUEST>", "").strip()
                        req_lines = [l for l in clean_content.splitlines() if not l.startswith("Other open documents:") and not l.startswith("The current local time:") and not l.startswith("- ") and not l.strip().startswith("d:\\")]
                        snippet = " ".join(req_lines)[:150]
                        print(f"File: {f} | Sender: {sender} | Snippet: {snippet}")
            except Exception as e:
                pass
else:
    print("Folder does not exist")
