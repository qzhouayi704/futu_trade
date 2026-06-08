import os
import json

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
                                content = file.read()
                                if any(keyword in content for keyword in ["新闻", "抓取", "crawler", "crawler", "fetcher", "futu_news"]):
                                    # Try to find the first user message or date
                                    created_at = "Unknown"
                                    # overview.txt might contain json lines
                                    first_line = content.splitlines()[0] if content else ""
                                    if first_line.startswith("{"):
                                        try:
                                            obj = json.loads(first_line)
                                            created_at = obj.get("created_at", "Unknown")
                                        except Exception:
                                            pass
                                    matches.append((folder, created_at, content[:300]))
                        except Exception as e:
                            print(f"Error reading {folder}/{f}: {e}")
                            
    # Sort matches by folder or created_at
    print(f"Found {len(matches)} matching conversations:")
    for folder, date, snippet in sorted(matches, key=lambda x: x[1], reverse=True):
        print(f"Folder: {folder} | Date: {date}")
        print(f"Snippet: {snippet.strip()[:200]}")
        print("-" * 50)
