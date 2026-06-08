import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
matches = []

if os.path.exists(brain_dir):
    for folder in os.listdir(brain_dir):
        if folder == "tempmediaStorage":
            continue
        msg_dir = os.path.join(brain_dir, folder, ".system_generated", "messages")
        if os.path.exists(msg_dir):
            for f in os.listdir(msg_dir):
                if f.endswith(".json") and f not in ["cursor.json", "read.json"]:
                    fp = os.path.join(msg_dir, f)
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                            data = json.load(file)
                            sender = data.get("sender", "")
                            content = data.get("content", "")
                            if content and ("新闻" in content or "news_crawler" in content or "futu_news" in content):
                                # It's a match!
                                mtime = os.path.getmtime(fp)
                                matches.append((folder, f, sender, mtime, content))
                    except Exception as e:
                        pass

print(f"Total matching messages: {len(matches)}")
# Group matches by folder and sort by the latest message time in that folder
from collections import defaultdict
grouped = defaultdict(list)
for folder, filename, sender, mtime, content in matches:
    grouped[folder].append((filename, sender, mtime, content))

sorted_folders = []
for folder, msgs in grouped.items():
    latest_mtime = max(m[2] for m in msgs)
    sorted_folders.append((folder, latest_mtime, msgs))

for folder, latest_mtime, msgs in sorted(sorted_folders, key=lambda x: x[1], reverse=True)[:10]:
    print(f"=== Folder: {folder} (Latest msg time: {latest_mtime}) ===")
    # Print user messages or unique snippets
    user_msgs = [m for m in msgs if m[1] == "user" or "USER_REQUEST" in m[3]]
    for filename, sender, mtime, content in sorted(user_msgs, key=lambda x: x[2])[:5]:
        clean = content.replace("<USER_REQUEST>\n", "").replace("\n</USER_REQUEST>", "").strip()
        lines = [l for l in clean.splitlines() if not l.startswith("Other open documents:") and not l.startswith("The current local time:") and not l.strip().startswith("d:\\")]
        text = " ".join(lines)[:250]
        print(f"  [{sender}] ({filename}): {text}")
    print("-" * 80)
