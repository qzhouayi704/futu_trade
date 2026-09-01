#!/usr/bin/env python3
"""Run V2 tests with only the Python standard library available."""

from importlib.util import find_spec
from pathlib import Path
from types import ModuleType
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]


def bootstrap_source_packages() -> None:
    if find_spec("fastapi") is not None:
        return
    packages = {
        "simple_trade": ROOT / "simple_trade",
        "simple_trade.api": ROOT / "simple_trade" / "api",
        "simple_trade.database": ROOT / "simple_trade" / "database",
        "simple_trade.database.core": ROOT / "simple_trade" / "database" / "core",
        "simple_trade.utils": ROOT / "simple_trade" / "utils",
    }
    for name, path in packages.items():
        module = ModuleType(name)
        module.__path__ = [str(path)]  # type: ignore[attr-defined]
        module.__package__ = name
        sys.modules.setdefault(name, module)


def main() -> int:
    bootstrap_source_packages()
    suite = unittest.defaultTestLoader.discover(
        str(ROOT / "tests" / "v2"),
        pattern="test_*.py",
        top_level_dir=str(ROOT),
    )
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main())
