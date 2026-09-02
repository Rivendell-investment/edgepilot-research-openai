from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    if "EDGEPILOT_RESEARCH_HOME" in os.environ:
        default = os.environ["EDGEPILOT_RESEARCH_HOME"]
    else:
        # This is unchanged on macOS/Linux.  On Windows, unlike APPDATA, the
        # profile home remains stable across packaged and unpackaged processes
        # and leaves enough of the legacy Win32 path budget for release venv
        # DLLs.  Microsoft Store/MSIX can virtualize an apparently ordinary
        # APPDATA path only when it is accessed, so inspecting its string is
        # not a reliable compatibility check.
        default = str(Path.home() / ".edgepilot-research")
    root = Path(default).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def bundled_root() -> Path:
    return Path(__file__).with_name("bundled")


def runtime_state_path() -> Path:
    return state_root() / "runtime.json"
