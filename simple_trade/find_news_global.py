import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
matches = []

if os.path.exists(brain_dir):
    for root, dirs, files in os.walk(brain_dir):
        if ".tempmediaStorage" in root:
            continue
        for f in files:
            if f == "overview.txt" or f == "transcript.jsonl":
                fp = os.path.join(root, f)
                if os.path.getsize(fp) > 0:
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                            content = file.read()
                            # Check if it talks about "新闻" or "news"
                            if "新闻" in content or "news_crawler" in content or "futu_news" in content:
                                rel = os.path.relpath(fp, brain_dir)
                                # Find first user request that matched
                                user_req = ""
                                for line in content.splitlines():
                                    if '"source":"USER_EXPLICIT"' in line and ('新闻' in line or 'news_crawler' in line or 'futu_news' in line or 'crawler' in line):
                                        try:
                                            obj = json.loads(line)
                                            raw = obj.get("content", "")
                                            clean = raw.split("<ADDITIONAL_METADATA>")[0].replace("<USER_REQUEST>", "").replace("</USER_REQUEST>", "").strip()
                                            user_req = clean.replace("\n", " ")
                                            break
                                        except:
                                            pass
                                matches.append((rel, os.path.getmtime(fp), user_req))
                    except Exception as e:
                        pass

print(f"Total matching sessions (overview.txt/transcript.jsonl): {len(matches)}")
for rel, mtime, user_req in sorted(matches, key=lambda x: x[1], reverse=True):
    print(f"File: {rel} (Mtime: {mtime})")
    print(f"  First Matching Request: {user_req[:250]}")
    print("-" * 70)
