import os
import json
import sys

# Set output to utf-8
sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
if os.path.exists(brain_dir):
    folders = os.listdir(brain_dir)
    matches = []
    for folder in folders:
        if folder == "tempmediaStorage":
            continue
        sub = os.path.join(brain_dir, folder, ".system_generated", "logs")
        if os.path.exists(sub):
            for f in os.listdir(sub):
                if f == "overview.txt":
                    fp = os.path.join(sub, f)
                    if os.path.getsize(fp) > 0:
                        try:
                            with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                                for line in file:
                                    if '"source":"USER_EXPLICIT"' in line:
                                        obj = json.loads(line)
                                        content = obj.get("content", "")
                                        # Search specifically for news-related words
                                        if any(k in content for k in ["新闻", "news", "futu_news", "抓取", "爬虫"]):
                                            created_at = obj.get("created_at", "")
                                            matches.append((folder, created_at, content))
                                            break
                        except Exception as e:
                            pass
                            
    print(f"Found {len(matches)} matching user inputs:")
    for folder, date, content in sorted(matches, key=lambda x: x[1], reverse=True):
        clean_content = content.replace("<USER_REQUEST>\n", "").replace("\n</USER_REQUEST>", "").strip()
        lines = clean_content.splitlines()
        req_lines = [l for l in lines if not l.startswith("Other open documents:") and not l.startswith("The current local time:") and not l.startswith("- ") and not l.strip().startswith("d:\\")]
        req_text = " ".join(req_lines)[:300]
        print(f"Folder: {folder} | Date: {date}")
        print(f"  Request: {req_text}")
        print("-" * 60)
