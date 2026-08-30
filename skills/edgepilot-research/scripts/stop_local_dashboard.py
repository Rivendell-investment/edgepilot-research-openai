#!/usr/bin/env python3
"""Inspect or stop only the verified bundled EdgePilot Research Dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys


PLUGIN_ROOT = Path(__file__).resolve().parents[3]
CORE = PLUGIN_ROOT / "core_src"
if not CORE.is_dir():
    CORE = PLUGIN_ROOT.parent / "edgepilot-core" / "src"
sys.path[:0] = [str(PLUGIN_ROOT / "src"), str(CORE)]

from edgepilot_core.local_mcp import (  # noqa: E402
    inspect_verified_embedded_dashboard,
    stop_verified_embedded_dashboard,
)
from edgepilot_research.paths import state_root  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Inspect the verified EdgePilot Research local Dashboard")
    parser.add_argument("--stop-if-running", action="store_true", help="Stop the verified idle Dashboard")
    args = parser.parse_args(argv)
    root = state_root()
    if args.stop_if_running:
        result = stop_verified_embedded_dashboard(root)
    else:
        identity = inspect_verified_embedded_dashboard(root)
        result = {
            "running": identity is not None,
            "version": identity.get("version") if identity is not None else None,
        }
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
