#!/usr/bin/env python3
"""Inspect a local paper session without initializing any broker or app services."""

import argparse
from pathlib import Path
import sys
from types import ModuleType


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
for name, path in (("simple_trade", ROOT / "simple_trade"),
                   ("simple_trade.utils", ROOT / "simple_trade" / "utils")):
    if name not in sys.modules:
        package = ModuleType(name)
        package.__path__ = [str(path)]
        package.__package__ = name
        sys.modules[name] = package

from simple_trade.v2.domain.planning.codec import encode
from simple_trade.v2.infrastructure.paper.session_report import read_session_report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(encode(read_session_report(args.db)))
    except Exception as error:
        print(f"Paper session inspection failed: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
