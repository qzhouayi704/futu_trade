"""Transfer the bounded read-only export to the current project."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', required=True)
    parser.add_argument('--today-focus', action='store_true')
    args = parser.parse_args()
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(output)
    source = Path(__file__).with_name('export.py').read_bytes()
    command = ['ssh', '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=8',
               '-i', r'C:\Users\ZHOUYICAN\.ssh\id_ed25519_server', '-p', '29122',
               'root@170.106.152.108', 'python3 -' + (' --today-focus' if args.today_focus else '')]
    process = subprocess.run(command, input=source, capture_output=True, timeout=120, check=True)
    data = json.loads(gzip.decompress(process.stdout))
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('xb') as stream:
        stream.write(process.stdout)
    print(json.dumps({'output': str(output), 'bytes': output.stat().st_size,
                      'sha256': hashlib.sha256(process.stdout).hexdigest(),
                      'events': len(data['events']), 'minutes': len(data['minutes']),
                      'days': sorted({r[1] for r in data['minutes']})}, ensure_ascii=False))


if __name__ == '__main__':
    main()
