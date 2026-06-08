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
        fp = os.path.join(brain_dir, folder, ".system_generated", "logs", "overview.txt")
        if os.path.exists(fp) and os.path.getsize(fp) > 0:
            try:
                with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                    for line in file:
                        if '"source":"USER_EXPLICIT"' in line:
                            obj = json.loads(line)
                            content = obj.get("content", "")
                            # Check if the content is about news scraping or news crawler
                            if any(k in content for k in ["新闻", "news", "futu_news", "抓取", "爬虫"]):
                                created_at = obj.get("created_at", "")
                                matches.append((folder, created_at, content))
                                # Don't break immediately so we can get all user requests from this folder
            except Exception as e:
                pass

print(f"Total matching user inputs in overview.txt: {len(matches)}")
for folder, date, content in sorted(matches, key=lambda x: x[1], reverse=True):
    # Print the user request detail
    print(f"=== Folder: {folder} | Date: {date} ===")
    print(content.strip())
    print("=" * 80)
