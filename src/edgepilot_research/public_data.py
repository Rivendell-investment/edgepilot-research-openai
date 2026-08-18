from __future__ import annotations

import asyncio
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from .paths import state_root

UTC = timezone.utc
ALLOWED_DAYS = {90, 365}


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
            if venue != "BINANCE" or market.data_type != "bars":
                raise ValueError(f"PUBLIC_DATA_UNSUPPORTED: automatic Research download supports Binance bars only, not {venue} {market.data_type}")
            settings = venue_values.get(venue, {})
            account_type = str(settings.get("account_type", ""))
            if account_type not in {"USDT_FUTURES", "COIN_FUTURES"}:
                raise ValueError("PUBLIC_DATA_UNSUPPORTED: Binance Research download requires a Futures account_type in the preset")
            asyncio.run(_download_binance(staging, market.instrument_id, market.bar_type, account_type, start, end))
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


async def _download_binance(
    catalog_path: Path,
    instrument_id: str,
    bar_type: str,
    account_type_name: str,
    start: datetime,
    end: datetime,
) -> None:
    from nautilus_trader.adapters.binance.common.enums import BinanceAccountType, BinanceEnvironment, BinanceKlineInterval
    from nautilus_trader.adapters.binance.factories import get_cached_binance_http_client
    from nautilus_trader.adapters.binance.futures.enums import BinanceFuturesEnumParser
    from nautilus_trader.adapters.binance.futures.http.market import BinanceFuturesMarketHttpAPI
    from nautilus_trader.adapters.binance.futures.providers import BinanceFuturesInstrumentProvider
    from nautilus_trader.common.component import LiveClock
    from nautilus_trader.config import InstrumentProviderConfig
    from nautilus_trader.model.data import Bar, BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    account_type = BinanceAccountType[account_type_name]
    identifier = InstrumentId.from_str(instrument_id)
    clock = LiveClock()
    client = get_cached_binance_http_client(
        clock=clock, account_type=account_type, api_key=None, api_secret=None,
        base_url=None, environment=BinanceEnvironment.LIVE, is_us=False, proxy_url=None,
    )
    provider = BinanceFuturesInstrumentProvider(
        client=client,
        clock=clock,
        account_type=account_type,
        config=InstrumentProviderConfig(load_all=False, load_ids=frozenset({identifier})),
    )
    await provider.initialize()
    instrument = provider.find(identifier)
    if instrument is None:
        raise ValueError(f"Binance did not return instrument {instrument_id}")
    parsed = BarType.from_str(bar_type)
    if not parsed.spec.is_time_aggregated() or not str(bar_type).endswith("-LAST-EXTERNAL"):
        raise ValueError(f"unsupported Binance Research bar type: {bar_type}")
    resolution = BinanceFuturesEnumParser().parse_nautilus_bar_aggregation(parsed.spec.aggregation)
    try:
        interval = BinanceKlineInterval(f"{parsed.spec.step}{resolution}")
    except ValueError as error:
        raise ValueError(f"unsupported Binance interval: {parsed.spec}") from error
    market = BinanceFuturesMarketHttpAPI(client, account_type=account_type)
    downloaded = await market.request_binance_bars(
        bar_type=parsed,
        interval=interval,
        start_time=int(start.timestamp() * 1_000),
        end_time=int(end.timestamp() * 1_000),
        limit=1_000,
    )
    interval_ns = int(parsed.spec.timedelta.total_seconds() * 1_000_000_000)
    catalog = ParquetDataCatalog(str(catalog_path))
    existing = {bar.ts_event for bar in catalog.bars(bar_types=[bar_type])}
    bars = []
    for bar in downloaded:
        values = Bar.to_dict(bar)
        close_ns = ((bar.ts_event + interval_ns - 1) // interval_ns) * interval_ns
        if close_ns in existing or close_ns > int(end.timestamp() * 1_000_000_000):
            continue
        values["ts_event"] = values["ts_init"] = close_ns
        bars.append(Bar.from_dict(values))
        existing.add(close_ns)
    catalog.write_data([instrument])
    if bars:
        _write_contiguous(catalog, bars, interval_ns)
    available = catalog.bars(bar_types=[bar_type])
    if not available or min(bar.ts_event for bar in available) > int(start.timestamp() * 1_000_000_000) + interval_ns or max(bar.ts_event for bar in available) < int(end.timestamp() * 1_000_000_000):
        raise ValueError(f"Binance returned incomplete {bar_type} data for {start.isoformat()} to {end.isoformat()}")


def _write_contiguous(catalog: Any, bars: list[Any], interval_ns: int) -> None:
    ordered = sorted(bars, key=lambda bar: bar.ts_event)
    segment = [ordered[0]]
    for bar in ordered[1:]:
        if bar.ts_event == segment[-1].ts_event + interval_ns:
            segment.append(bar)
        else:
            catalog.write_data(segment)
            segment = [bar]
    catalog.write_data(segment)
