"""Reviewed Binance Futures public bars.

Nautilus stamps a completed Binance kline at its close, so the canonical window
needs no shift here; only the native request has to be expressed in Binance's
open-time parameters.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from ._common import (
    canonical_close_window,
    external_bar_interval_ns,
    https_proxy_url,
    verify_window,
    write_contiguous,
)

VENUE = "BINANCE"
ACCOUNT_TYPES = {"USDT_FUTURES", "COIN_FUTURES"}


def unsupported_reason(market: Any, settings: dict[str, Any]) -> str | None:
    if market.data_type != "bars":
        return f"automatic Research download supports bars only, not {VENUE} {market.data_type}"
    if str(settings.get("account_type", "")) not in ACCOUNT_TYPES:
        return "Binance Research download requires a Futures account_type in the preset"
    return None


def request_window(
    start: datetime,
    end: datetime,
    interval_ns: int,
) -> tuple[int, int, int, int]:
    """Map the canonical [start, end) close window to Binance open times."""
    first_close_ns, last_close_ns = canonical_close_window(start, end, interval_ns)
    return (
        (first_close_ns - interval_ns) // 1_000_000,
        (last_close_ns - interval_ns) // 1_000_000,
        first_close_ns,
        last_close_ns,
    )


async def download(
    catalog_path: Path,
    market: Any,
    settings: dict[str, Any],
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

    instrument_id = market.instrument_id
    bar_type = market.bar_type
    account_type = BinanceAccountType[str(settings.get("account_type", ""))]
    identifier = InstrumentId.from_str(instrument_id)
    clock = LiveClock()
    client = get_cached_binance_http_client(
        clock=clock, account_type=account_type, api_key=None, api_secret=None,
        base_url=None, environment=BinanceEnvironment.LIVE, is_us=False,
        proxy_url=https_proxy_url(),
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
    interval_ns = external_bar_interval_ns(bar_type, VENUE)
    parsed = BarType.from_str(bar_type)
    resolution = BinanceFuturesEnumParser().parse_nautilus_bar_aggregation(parsed.spec.aggregation)
    try:
        interval = BinanceKlineInterval(f"{parsed.spec.step}{resolution}")
    except ValueError as error:
        raise ValueError(f"unsupported Binance interval: {parsed.spec}") from error
    request_start_ms, request_end_ms, first_close_ns, last_close_ns = request_window(
        start,
        end,
        interval_ns,
    )
    api = BinanceFuturesMarketHttpAPI(client, account_type=account_type)
    downloaded = await api.request_binance_bars(
        bar_type=parsed,
        interval=interval,
        start_time=request_start_ms,
        end_time=request_end_ms,
        limit=1_000,
    )
    catalog = ParquetDataCatalog(str(catalog_path))
    existing = {bar.ts_event for bar in catalog.bars(bar_types=[bar_type])}
    bars = []
    for bar in downloaded:
        values = Bar.to_dict(bar)
        close_ns = ((bar.ts_event + interval_ns - 1) // interval_ns) * interval_ns
        if close_ns < first_close_ns or close_ns > last_close_ns or close_ns in existing:
            continue
        values["ts_event"] = values["ts_init"] = close_ns
        bars.append(Bar.from_dict(values))
        existing.add(close_ns)
    catalog.write_data([instrument])
    if bars:
        write_contiguous(catalog, bars, interval_ns)
    verify_window(catalog, bar_type, VENUE, first_close_ns, last_close_ns, start, end)
