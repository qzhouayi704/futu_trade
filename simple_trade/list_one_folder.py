import os

folder = r"C:\Users\ZHOUYICAN\.gemini\antigravity-ide\brain\6b9ebb88-a359-4761-b630-ac6b415271e7"
if os.path.exists(folder):
    for root, dirs, files in os.walk(folder):
        for f in files:
            fp = os.path.join(root, f)
            print(f"File: {os.path.relpath(fp, folder)} | Size: {os.path.getsize(fp)} bytes")
else:
    print("Folder does not exist")
