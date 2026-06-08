import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

fp = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain\4b55c0ea-6fe2-432d-b83e-c99db0ca1db4\.system_generated\logs\overview.txt"
if os.path.exists(fp):
    print("=== 4b55c0ea-6fe2-432d-b83e-c99db0ca1db4/overview.txt ===")
    with open(fp, "r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            try:
                obj = json.loads(line)
                if obj.get("source") == "USER_EXPLICIT" and obj.get("type") == "USER_INPUT":
                    print(f"[{obj.get('created_at')}] User request:")
                    print(obj.get("content"))
                    print("-" * 50)
            except:
                pass
else:
    print("File does not exist")
