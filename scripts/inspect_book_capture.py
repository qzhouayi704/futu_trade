"""Read-only capture health report. Never starts SDK connections or trading."""

import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from simple_trade.v2.infrastructure.book_capture.archive import read_archive


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a sampled order-book archive (read-only)")
    parser.add_argument("--db", required=True, type=Path)
    args = parser.parse_args()
    try:
        report = read_archive(args.db)
    except Exception as error:
        print(f"Capture inspection failed: {error}", file=sys.stderr)
        return 1
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
