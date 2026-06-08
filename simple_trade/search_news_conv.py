import os
import json

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
if os.path.exists(brain_dir):
    for folder in os.listdir(brain_dir):
        if folder == "tempmediaStorage":
            continue
        transcript_path = os.path.join(brain_dir, folder, ".system_generated", "logs", "transcript.jsonl")
        if os.path.exists(transcript_path):
            has_match = False
            matches = []
            try:
                with open(transcript_path, "r", encoding="utf-8") as f:
                    for line_num, line in enumerate(f):
                        if "新闻" in line or "news_crawler" in line or "爬虫" in line or "fetcher" in line:
                            data = json.loads(line)
                            content = data.get("content", "")
                            if content and len(content.strip()) > 0:
                                matches.append((line_num, content[:150].replace("\n", " ")))
                                has_match = True
                if has_match:
                    print(f"=== Folder: {folder} ===")
                    for idx, snippet in matches[:3]:
                        print(f"  Line {idx}: {snippet}")
            except Exception as e:
                print(f"Error reading {folder}: {e}")
