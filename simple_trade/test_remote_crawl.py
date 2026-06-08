import subprocess
import json

ssh_key = r"C:\Users\ZHOUYICAN\.ssh\id_ed25519_server"
ssh_port = "29122"
ssh_user_host = "root@170.106.152.108"

# Remote python script to execute
remote_script = """
import urllib.request
import json
import time

url = "http://127.0.0.1:5001/api/news/crawl"
data = json.dumps({"max_items": 5, "debug": False}).encode("utf-8")
req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req) as response:
        res_data = json.loads(response.read().decode("utf-8"))
        print(json.dumps(res_data))
except Exception as e:
    print(json.dumps({"success": False, "message": str(e)}))
"""

cmd = [
    "ssh",
    "-i", ssh_key,
    "-p", ssh_port,
    ssh_user_host,
    "python3"
]

print("Executing SSH command...")
result = subprocess.run(cmd, input=remote_script, capture_output=True, text=True, encoding="utf-8")
print("Exit code:", result.returncode)
print("Stdout:", result.stdout)
print("Stderr:", result.stderr)
