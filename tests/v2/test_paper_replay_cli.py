import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]


class PaperReplayCliTests(unittest.TestCase):
    def test_standalone_replay_is_persistent_idempotent_and_never_loads_app(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / "scripts/paper_trade_replay.py"),
                       "--input", str(ROOT / "tests/fixtures/paper_replay_v1.json"),
                       "--ledger", str(Path(directory) / "paper.db")]
            first = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
            second = subprocess.run(command, capture_output=True, text=True, timeout=30, check=True)
            result = json.loads(first.stdout)
            self.assertEqual(json.loads(second.stdout), result)
            self.assertEqual(result["mode"], "OFFLINE_PAPER_ONLY")
            self.assertEqual(result["plan_count"], 1)
            self.assertEqual(result["fill_count"], 3)
            self.assertEqual(result["net_pnl"], "779.20")
            self.assertEqual(result["orders"][0]["status"], "CLOSED")
            self.assertEqual(result["open_positions"], 0)
            self.assertEqual(first.stderr, "")
