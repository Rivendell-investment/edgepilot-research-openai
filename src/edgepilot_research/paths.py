from __future__ import annotations

import os
from pathlib import Path


def _usable_windows_appdata() -> str | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    normalized = appdata.replace("/", "\\").lower()
    # Packaged hosts (for example Codex Desktop) redirect %APPDATA% into a deep
    # ...\Packages\<app>\LocalCache\Roaming prefix. Content-addressed releases
    # plus .venv\Lib\site-packages stacked on that prefix exceed the Windows DLL
    # load path limit, so fall back to the short per-user home instead.
    if "\\packages\\" in normalized and "\\localcache\\" in normalized:
        return None
    return appdata


def state_root() -> Path:
    if "EDGEPILOT_RESEARCH_HOME" in os.environ:
        default = os.environ["EDGEPILOT_RESEARCH_HOME"]
    elif os.name == "nt" and _usable_windows_appdata():
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
