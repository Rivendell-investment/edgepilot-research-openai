from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import state_root
from .public_data_venues import provider_for, supported_venues

UTC = timezone.utc
ALLOWED_DAYS = {90, 365}

__all__ = [
    "ALLOWED_DAYS",
    "ensure_public_data",
    "research_period",
    "supported_venues",
]


def research_period(days: int, markets: tuple[Any, ...], now: datetime | None = None) -> tuple[datetime, datetime]:
    if days not in ALLOWED_DAYS:
        raise ValueError(f"days must be one of: {', '.join(str(value) for value in sorted(ALLOWED_DAYS))}")
    try:
        from nautilus_trader.model.data import BarType
        intervals = [BarType.from_str(market.bar_type).spec.timedelta for market in markets]
    except Exception as error:
        raise ValueError(f"strategy contains an unsupported bar type: {error}") from error
    if not intervals or any(interval.total_seconds() <= 0 for interval in intervals):
        raise ValueError("strategy requires at least one time-aggregated bar market")
    step = max(intervals)
    current = (now or datetime.now(UTC)).astimezone(UTC)
    seconds = int(current.timestamp())
    end = datetime.fromtimestamp(seconds - seconds % int(step.total_seconds()), tz=UTC)
    return end - timedelta(days=days), end


def ensure_public_data(
    markets: tuple[Any, ...],
    venue_values: dict[str, dict[str, Any]],
    start: datetime,
    end: datetime,
) -> None:
    """Atomically refresh the selected public bar markets without credentials."""
    root = state_root()
    target = root / "catalog"
    lock = root / ".catalog-download.lock"
    try:
        lock.mkdir()
    except FileExistsError as error:
        raise ValueError("another catalog download is already running") from error
    staging = Path(tempfile.mkdtemp(prefix=".catalog-download-", dir=root))
    backup = root / f".catalog-download-previous-{staging.name.rsplit('-', 1)[-1]}"
    try:
        if target.exists():
            shutil.copytree(target, staging, dirs_exist_ok=True)
        for market in markets:
            venue = str(market.venue).upper()
            provider = provider_for(venue)
            if provider is None:
                raise ValueError(
                    f"PUBLIC_DATA_UNSUPPORTED: automatic Research download supports "
                    f"{', '.join(supported_venues())} bars only, not {venue} {market.data_type}",
                )
            settings = venue_values.get(venue, {})
            reason = provider.unsupported_reason(market, settings)
            if reason is not None:
                raise ValueError(f"PUBLIC_DATA_UNSUPPORTED: {reason}")
            asyncio.run(provider.download(staging, market, settings, start, end))
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.rename(backup)
        staging.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    except ValueError:
        raise
    except Exception as error:
        raise ValueError(f"PUBLIC_DATA_DOWNLOAD_FAILED: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        if not target.exists() and backup.exists():
            backup.rename(target)
        elif backup.exists():
            shutil.rmtree(backup)
        lock.rmdir()
