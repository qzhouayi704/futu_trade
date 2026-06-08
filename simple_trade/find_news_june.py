import os
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

matches = []
for folder in june_folders:
    folder_path = os.path.join(brain_dir, folder)
    if os.path.exists(folder_path):
        for root, dirs, files in os.walk(folder_path):
            for f in files:
                if f.endswith((".txt", ".json", ".jsonl", ".md")):
                    fp = os.path.join(root, f)
                    if os.path.getsize(fp) > 0:
                        try:
                            with open(fp, "r", encoding="utf-8", errors="ignore") as file:
                                content = file.read()
                                if "新闻" in content or "news" in content or "crawler" in content:
                                    rel = os.path.relpath(fp, brain_dir)
                                    # Find context
                                    idx = content.find("新闻")
                                    if idx == -1:
                                        idx = content.find("news")
                                    snippet = content[max(0, idx-100):min(len(content), idx+200)]
                                    matches.append((rel, os.path.getmtime(fp), snippet))
                        except Exception:
                            pass

print(f"Total matching files in June folders: {len(matches)}")
for rel, mtime, snippet in sorted(matches, key=lambda x: x[1], reverse=True)[:30]:
    print(f"File: {rel} (Mtime: {mtime})")
    print(f"Snippet: {snippet.strip().replace('\n', ' ')}")
    print("-" * 60)
