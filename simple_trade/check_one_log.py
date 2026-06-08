import os
import json

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
folder = "aeb22ca2-6690-45c5-bfd7-6412be9fc0df"
fp = os.path.join(brain_dir, folder, ".system_generated", "logs", "overview.txt")
if os.path.exists(fp):
    print("=== aeb22ca2-6690-45c5-bfd7-6412be9fc0df ===")
    with open(fp, "r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            try:
                obj = json.loads(line)
                print(f"[{obj.get('source')}] type: {obj.get('type')}")
                content = obj.get('content', '')
                if content:
                    print("Content:", content[:200])
            except Exception as e:
                pass

# Let's search other folders around 2026-05-15 for more news/crawling.
# Wait, look at this snippet: "系统抓取脚本啊，每次对话都抓取"
# Let's search for "新闻" or "news" or "抓取" or "futu" in logs of recent 2-3 conversations.
# Let's find files that contain these words and print their full content.
