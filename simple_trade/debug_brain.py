import os

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
print("Brain dir exists:", os.path.exists(brain_dir))
if os.path.exists(brain_dir):
    folders = os.listdir(brain_dir)
    print("Folders in brain dir:", folders)
    for folder in folders:
        if folder == "tempmediaStorage":
            continue
        sub = os.path.join(brain_dir, folder, ".system_generated", "logs")
        if os.path.exists(sub):
            print(f"Logs subfolder exists for {folder}: {os.listdir(sub)}")
            trans_path = os.path.join(sub, "transcript.jsonl")
            if os.path.exists(trans_path):
                print(f"  transcript.jsonl size: {os.path.getsize(trans_path)} bytes")
        else:
            print(f"Logs subfolder does NOT exist for {folder}")
