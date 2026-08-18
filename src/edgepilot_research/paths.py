from __future__ import annotations

import os
from pathlib import Path


def state_root() -> Path:
    if "EDGEPILOT_RESEARCH_HOME" in os.environ:
        default = os.environ["EDGEPILOT_RESEARCH_HOME"]
    elif os.name == "nt" and os.environ.get("APPDATA"):
        default = str(Path(os.environ["APPDATA"]) / "EdgePilotResearch")
    else:
        default = str(Path.home() / ".edgepilot-research")
    root = Path(default).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    return root


def bundled_root() -> Path:
    return Path(__file__).with_name("bundled")


def runtime_state_path() -> Path:
    return state_root() / "runtime.json"
