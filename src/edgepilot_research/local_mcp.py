#!/usr/bin/env python3
"""EdgePilot Research local stdio MCP entry point."""

from __future__ import annotations

from pathlib import Path
import sys
from http.server import ThreadingHTTPServer

PRODUCT_ROOT = Path(__file__).resolve().parents[2]
CORE = PRODUCT_ROOT / "core_src"
if not CORE.is_dir():
    CORE = PRODUCT_ROOT.parent / "edgepilot-core" / "src"
sys.path[:0] = [str(PRODUCT_ROOT / "src"), str(CORE)]

from edgepilot_core.local_mcp import ProductConfig, run  # noqa: E402
from edgepilot_research import __version__  # noqa: E402
from edgepilot_research.marketplace import recommend  # noqa: E402
from edgepilot_research.paths import state_root  # noqa: E402


def _dashboard_server(host: str, port: int) -> ThreadingHTTPServer:
    from edgepilot_research.ui import Handler
    server = ThreadingHTTPServer((host, port), Handler)
    server.research_csrf = __import__("secrets").token_urlsafe(32)  # type: ignore[attr-defined]
    return server


if __name__ == "__main__":
    raise SystemExit(run(ProductConfig(
        name="EdgePilot Research",
        server_name="edgepilot-research",
        version=__version__,
        state_root=state_root(),
        default_port=8686,
        ui_uri="ui://edgepilot-research/strategy-cards/v2.html",
        lifecycle_prompt=("EdgePilot Research 已自动启动本地网站（仅本机可访问）。关闭 ChatGPT 或停用 EdgePilot Research 后，"
                          "网站会自动关闭。若希望退出 ChatGPT 后仍在本机后台运行并随系统启动，请回复："
                          "让 EdgePilot Research 长期运行。"),
        service_id="capital.rivendell.edgepilot.research.dashboard",
        windows_task=r"\EdgePilot\Research Dashboard",
        identity_attribute="research_identity",
    ), recommend, _dashboard_server))
