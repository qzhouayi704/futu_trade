import os

brain_dir = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain"
if os.path.exists(brain_dir):
    for folder in os.listdir(brain_dir):
        if folder == "tempmediaStorage":
            continue
        sub = os.path.join(brain_dir, folder, ".system_generated", "logs")
        if os.path.exists(sub):
            files = os.listdir(sub)
            # Find files with size > 0
            for f in files:
                fp = os.path.join(sub, f)
                sz = os.path.getsize(fp)
                if sz > 0:
                    print(f"Folder: {folder} | File: {f} | Size: {sz} bytes")
