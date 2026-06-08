import os
import json
import sys

sys.stdout.reconfigure(encoding='utf-8')

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
june_folders = [
    "bd7aa066-725e-4f39-999c-77c6eff22d92",
    "6b9ebb88-a359-4761-b630-ac6b415271e7",
    "30565423-69e0-403b-b418-876fe995bcc6",
    "2bc65a23-4291-4bb2-8fa7-096001b175b4",
    "d3c61bc4-f9c8-4078-9804-97dde58c85f5",
    "58b86936-db60-4212-adaf-7c293a4881ab",
    "23dbdf02-4b7c-41f2-9113-330546138a86",
    "85cac632-fd0b-4a49-8a05-5ce04de65029",
    "015b9083-99be-4d6d-8422-75e8ab3c8d7c",
    "28a96e66-6436-44e3-88da-7c35088c5086",
    "e72193a9-ab88-48a4-80c7-87aaceaf0cd5",
    "1a297407-6199-4bc4-b493-9576b77cf462",
    "ea6beb3b-2cd6-4647-9674-3149550bbb35",
    "703382ef-19ee-44b8-bd52-01d99e2549ab",
    "b7ea4beb-43fb-4f2a-afbb-772ef86faafd",
    "004bd157-e836-47f0-9beb-f45175262753"
]

for folder in june_folders:
    fp = os.path.join(brain_dir, folder, ".system_generated", "logs", "transcript.jsonl")
    if os.path.exists(fp) and os.path.getsize(fp) > 0:
        print(f"=== Folder: {folder} (transcript.jsonl) ===")
        with open(fp, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()
            # print first and last user input
            user_inputs = []
            for line in lines:
                try:
                    obj = json.loads(line)
                    if obj.get("source") == "USER_EXPLICIT" and obj.get("type") == "USER_INPUT":
                        content = obj.get("content", "")
                        clean_content = content.replace("<USER_REQUEST>\n", "").replace("\n</USER_REQUEST>", "").strip()
                        req_lines = [l for l in clean_content.splitlines() if not l.startswith("Other open documents:") and not l.startswith("The current local time:") and not l.startswith("- ") and not l.strip().startswith("d:\\")]
                        user_inputs.append((obj.get("created_at", ""), " ".join(req_lines)[:200]))
                except Exception:
                    pass
            if user_inputs:
                print(f"  First user input: {user_inputs[0][0]} | {user_inputs[0][1]}")
                print(f"  Last user input: {user_inputs[-1][0]} | {user_inputs[-1][1]}")
                print(f"  Total user inputs: {len(user_inputs)}")
            else:
                print("  No user inputs found.")
            
            # Search for news/新聞 inside all lines
            matching_lines = 0
            for idx, line in enumerate(lines):
                if any(k in line for k in ["新闻", "news", "futu_news", "抓取", "爬虫"]):
                    matching_lines += 1
            print(f"  Total news-related lines: {matching_lines}")
        print("-" * 50)
