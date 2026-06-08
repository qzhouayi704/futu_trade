import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
files = [
    r"03ad9d03-badc-41aa-a005-91f2385b6eed\.system_generated\logs\overview.txt",
    r"b24e70aa-3c2d-4fe3-9881-9efa3774eb58\.system_generated\logs\overview.txt",
    r"bee18875-382f-48f0-b303-50f95d583a68\.system_generated\logs\overview.txt"
]

for f in files:
    fp = os.path.join(brain_dir, f)
    if os.path.exists(fp):
        print(f"=== File: {f} ===")
        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
            count = 0
            for line in file:
                try:
                    obj = json.loads(line)
                    if obj.get("source") == "USER_EXPLICIT" and obj.get("type") == "USER_INPUT":
                        content = obj.get("content", "")
                        clean = content.split("<ADDITIONAL_METADATA>")[0].replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                        print(f"  [{obj.get('created_at')}] {clean[:150]}")
                        count += 1
                        if count >= 15:
                            print("  (truncated)")
                            break
                except:
                    pass
        print("-" * 75)
