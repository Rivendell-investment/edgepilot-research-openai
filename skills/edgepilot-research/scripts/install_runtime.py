#!/usr/bin/env python3
"""Install the immutable EdgePilot Research native runtime."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    plugin_root = Path(__file__).resolve().parents[3]
    sys.path.insert(0, str(plugin_root / "src"))
    from edgepilot_research.runtime import install_runtime

    parser = argparse.ArgumentParser(description="Install the locked EdgePilot Research runtime")
    parser.add_argument("--accept-runtime-download", action="store_true")
    parser.add_argument("--wheelhouse", type=Path, help="optional directory containing any matching locked wheels")
    args = parser.parse_args()
    state = install_runtime(
        plugin_root,
        plugin_root / "runtime-lock.json",
        accept_download=args.accept_runtime_download,
        wheelhouse=args.wheelhouse,
    )
    print(json.dumps(state, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
