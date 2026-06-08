import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
matches = []

if os.path.exists(brain_dir):
    for root, dirs, files in os.walk(brain_dir):
        for f in files:
            if f.endswith((".txt", ".json", ".jsonl", ".md")):
                fp = os.path.join(root, f)
                if os.path.getsize(fp) > 0:
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                            content = file.read()
                            if "2bc65a23-4291-4bb2-8fa7-096001b175b4" in content:
                                rel = os.path.relpath(fp, brain_dir)
                                matches.append(rel)
                    except:
                        pass

print("Files referring to 2bc65a23-4291-4bb2-8fa7-096001b175b4:")
for m in matches:
    print(m)
