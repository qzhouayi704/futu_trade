import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

fp = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain\d14e01fe-4221-4a03-a30d-5d362f651f7d\.system_generated\logs\overview.txt"
if os.path.exists(fp):
    print("=== d14e01fe-4221-4a03-a30d-5d362f651f7d/overview.txt ===")
    with open(fp, "r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            try:
                obj = json.loads(line)
                if obj.get("source") == "USER_EXPLICIT" and obj.get("type") == "USER_INPUT":
                    print(f"[{obj.get('created_at')}] User request:")
                    content = obj.get("content")
                    # print content but filter out ADDITONAL_METADATA to keep it clean
                    clean_content = content.split("<ADDITIONAL_METADATA>")[0].strip()
                    print(clean_content)
                    print("-" * 50)
            except:
                pass
else:
    print("File does not exist")
