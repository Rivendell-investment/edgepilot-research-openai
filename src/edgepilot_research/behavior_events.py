from __future__ import annotations

import json
import os
import urllib.request
import uuid
from typing import Any

from . import __version__
from .marketplace import ORIGIN
from .paths import state_root


def _installation_id() -> str:
    path = state_root() / "behavior-installation-id"
    try:
        return str(uuid.UUID(path.read_text(encoding="ascii").strip()))
    except (OSError, ValueError):
        value = uuid.uuid4()
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return str(uuid.UUID(path.read_text(encoding="ascii").strip()))
    with os.fdopen(descriptor, "w", encoding="ascii") as stream:
        stream.write(str(value))
    return str(value)


def record_behavior_event(payload: dict[str, Any]) -> None:
    body = {**payload, "installation_id": _installation_id(), "client_version": __version__}
    request = urllib.request.Request(f"{ORIGIN}/api/research/behavior-events",
        data=json.dumps(body, separators=(",", ":")).encode("utf-8"), method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": f"edgepilot-research/{__version__}"})
    with urllib.request.urlopen(request, timeout=5) as response:
        response.read(4097)
