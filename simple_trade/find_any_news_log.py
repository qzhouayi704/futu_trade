import os
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
if os.path.exists(brain_dir):
    matches = []
    for root, dirs, files in os.walk(brain_dir):
        for f in files:
            if f.endswith(".txt") or f.endswith(".jsonl") or f.endswith(".json"):
                fp = os.path.join(root, f)
                if os.path.getsize(fp) > 0:
                    try:
                        with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                            content = file.read()
                            if "新闻" in content or "futu_news" in content:
                                # Find folder name from root
                                rel = os.path.relpath(fp, brain_dir)
                                matches.append((rel, os.path.getmtime(fp), content[:200]))
                    except Exception as e:
                        pass
                        
    print(f"Total matches across all files: {len(matches)}")
    for rel_path, mtime, snippet in sorted(matches, key=lambda x: x[1], reverse=True)[:20]:
        print(f"Path: {rel_path} | Mtime: {mtime}")
        print(f"Snippet: {snippet.strip()}")
        print("-" * 50)
