"""Finite-retry, timeout-bounded read-only export transport."""
import argparse
import gzip
import hashlib
import json
from pathlib import Path
import subprocess


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--audit',action='store_true',help='Export historical coverage summaries, not another backtest dataset')
    group.add_argument('--audit-legacy',action='store_true',help='Export older event-time plate-name evidence')
    group.add_argument('--legacy-replay',action='store_true',help='Export legacy events and full subsequent minute paths')
    group.add_argument('--forward-readiness',action='store_true',help='Probe available dates without starting an experiment')
    group.add_argument('--forward-intake',action='store_true',help='Read-only focus-stock source contract evidence, not performance data')
    group.add_argument('--forward-stage-counts',action='store_true',help='Authorized HK date/stage aggregate counts only; no individual records')
    group.add_argument('--forward-two-sequences',action='store_true',help='Only the two authorized FIRST sequences at the frozen 11:36 snapshot')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError(args.output)
    command = ['ssh','-o','BatchMode=yes','-o','ConnectTimeout=8','-i',
               r'C:\Users\ZHOUYICAN\.ssh\id_ed25519_server','-p','29122','root@170.106.152.108','python3 -']
    source_path = Path(__file__).parent/'audit'/'export.py' if args.audit else Path(__file__).with_name('export.py')
    if args.audit_legacy:
        source_path = Path(__file__).parent/'audit'/'legacy_export.py'
    if args.legacy_replay:
        source_path = Path(__file__).parent/'legacy'/'export.py'
    if args.forward_readiness:
        source_path = Path(__file__).parent/'forward'/'probe.py'
    if args.forward_intake:
        source_path = Path(__file__).parent/'forward'/'intake'/'export.py'
    if args.forward_stage_counts:
        source_path = Path(__file__).parent/'forward'/'intake'/'stage_probe.py'
    if args.forward_two_sequences:
        source_path = Path(__file__).parent/'forward'/'intake'/'episode_probe.py'
    source = source_path.read_bytes()
    for attempt in range(2):
        try:
            result = subprocess.run(command,input=source,capture_output=True,timeout=150,check=True)
            break
        except (subprocess.TimeoutExpired,subprocess.CalledProcessError):
            if attempt:
                raise
    data = json.loads(gzip.decompress(result.stdout))
    args.output.parent.mkdir(parents=True,exist_ok=True)
    with args.output.open('xb') as stream:
        stream.write(result.stdout)
    print(json.dumps({'file':str(args.output),'sha256':hashlib.sha256(result.stdout).hexdigest(),
                      'bytes':len(result.stdout),'kind':data.get('kind','SWING_DATA'),
                      'events':len(data.get('events',data.get('candidates',data.get('theme_events',data.get('signals',[]))))),
                      'minutes':len(data.get('minutes',[])),'coverage_stock_days':len(data.get('coverage',[])),
                      'summary_rows':len(data.get('counts',[])),
                      'sequences':len(data.get('sequences',[])),
                      'daily':len(data.get('daily',[])),'days':[row[0] for row in data.get('archives',[])]}))


if __name__ == '__main__':
    main()
