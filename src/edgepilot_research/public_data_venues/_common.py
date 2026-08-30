"""Helpers shared by the reviewed public market-data providers."""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime
from typing import Any

PROGRESS_PREFIX = "EDGEPILOT_PROGRESS "


def canonical_close_window(
    start: datetime,
    end: datetime,
    interval_ns: int,
) -> tuple[int, int]:
    """Return the first and last completed bar closes in canonical ``[start, end)``."""
    if interval_ns <= 0:
        raise ValueError("Research bar interval must be positive")
    start_ns = int(start.timestamp() * 1_000_000_000)
    end_ns = int(end.timestamp() * 1_000_000_000)
    first_close_ns = ((start_ns + interval_ns - 1) // interval_ns) * interval_ns
    last_close_ns = ((end_ns - 1) // interval_ns) * interval_ns
    if first_close_ns > last_close_ns:
        raise ValueError("Research period contains no complete bar close")
    return first_close_ns, last_close_ns


def https_proxy_url() -> str | None:
    """Forward a standard process-local HTTPS proxy to the native client."""
    return os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or None


def external_bar_interval_ns(bar_type: str, venue: str) -> int:
    """Validate a preset bar type for public download and return its interval."""
    from nautilus_trader.model.data import BarType

    parsed = BarType.from_str(bar_type)
    if not parsed.spec.is_time_aggregated() or not str(bar_type).endswith("-LAST-EXTERNAL"):
        raise ValueError(f"unsupported {venue} Research bar type: {bar_type}")
    return int(parsed.spec.timedelta.total_seconds() * 1_000_000_000)


def report_progress(stage: str, message: str, done: int | None = None, total: int | None = None) -> None:
    """Emit one machine-readable progress line for the Dashboard job supervisor.

    The Dashboard runs a backtest as a child process and reads its combined
    output, so progress travels as a prefixed single line that stays separable
    from the final result JSON.
    """
    payload: dict[str, Any] = {"stage": stage, "message": message, "done": done, "total": total}
    print(PROGRESS_PREFIX + json.dumps(payload, ensure_ascii=False), file=sys.stderr, flush=True)


def write_contiguous(catalog: Any, bars: list[Any], interval_ns: int) -> None:
    """Write bars as contiguous runs so the catalog keeps one file per unbroken segment."""
    ordered = sorted(bars, key=lambda bar: bar.ts_event)
    segment = [ordered[0]]
    for bar in ordered[1:]:
        if bar.ts_event == segment[-1].ts_event + interval_ns:
            segment.append(bar)
        else:
            catalog.write_data(segment)
            segment = [bar]
    catalog.write_data(segment)


def verify_window(
    catalog: Any,
    bar_type: str,
    venue: str,
    first_close_ns: int,
    last_close_ns: int,
    start: datetime,
    end: datetime,
) -> None:
    """Fail unless the catalog now spans the whole canonical close window."""
    available = catalog.bars(bar_types=[bar_type])
    if not available or min(bar.ts_event for bar in available) > first_close_ns \
            or max(bar.ts_event for bar in available) < last_close_ns:
        raise ValueError(f"{venue} returned incomplete {bar_type} data for {start.isoformat()} to {end.isoformat()}")
