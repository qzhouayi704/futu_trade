import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

folder = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain\2bc65a23-4291-4bb2-8fa7-096001b175b4"
if os.path.exists(folder):
    for root, dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            print(f"File: {os.path.relpath(fp, folder)} | Size: {os.path.getsize(fp)} bytes")
            # If it's a JSON/text file, print some lines
            if f.endswith((".json", ".txt", ".jsonl")):
                with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                    if f.endswith(".json"):
                        try:
                            data = json.load(file)
                            if "content" in data:
                                print("  Content:", str(data["content"])[:300].replace("\n", " "))
                        except:
                            pass
                    elif f.endswith(".txt") or f.endswith(".jsonl"):
                        print("  Lines:", file.read()[:300].replace("\n", " "))
