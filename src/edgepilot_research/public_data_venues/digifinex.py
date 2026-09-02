"""DigiFinex Swap perpetual public bars for Research catalog refreshes.

The Research path is deliberately credential-free and always targets the
production public host.  DigiFinex's native candle parser preserves the
exchange timestamp (milliseconds), which is the canonical completed-bar slot
used by the reviewed Live catalog downloader as well.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time
from typing import Any

from ._common import (
    canonical_close_window,
    external_bar_interval_ns,
    report_progress,
    verify_window,
    write_contiguous,
)

UTC = timezone.utc
VENUE = "DIGIFINEX"


def unsupported_reason(market: Any, settings: dict[str, Any]) -> str | None:
    """Return a user-facing reason when a market is outside this provider's scope."""
    if market.data_type != "bars":
        return f"automatic Research download supports bars only, not {VENUE} {market.data_type}"
    return None


def _moment(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, UTC)


async def download(
    catalog_path: Path,
    market: Any,
    settings: dict[str, Any],
    start: datetime,
    end: datetime,
) -> None:
    """Download and verify a DigiFinex public candle window atomically upstream."""
    from urllib.request import Request, urlopen

    from nautilus_trader.adapters.digifinex.constants import DIGIFINEX_LIVE_HTTP_BASE_URL
    from nautilus_trader.adapters.digifinex.data import request_digifinex_bars_paginated
    from nautilus_trader.adapters.digifinex.http import DigifinexHttpClient
    from nautilus_trader.adapters.digifinex.parsing import digifinex_granularity_from_bar_type
    from nautilus_trader.adapters.digifinex.providers import instrument_from_digifinex
    from nautilus_trader.adapters.digifinex.symbol import parse_digifinex_instrument_id
    from nautilus_trader.model.data import BarType
    from nautilus_trader.model.identifiers import InstrumentId
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    def _opener(request: Request, timeout: float | None = None) -> Any:
        request.add_header("User-Agent", "edgepilot-research")
        return urlopen(request, timeout=timeout)  # noqa: S310 - fixed HTTPS base URL

    bar_type = BarType.from_str(market.bar_type)
    interval_ns = external_bar_interval_ns(market.bar_type, VENUE)
    digifinex_granularity_from_bar_type(bar_type)  # fail early with a clear interval error
    instrument_id = InstrumentId.from_str(market.instrument_id)
    raw_symbol = parse_digifinex_instrument_id(instrument_id)
    client = DigifinexHttpClient(
        api_key=None,
        api_secret=None,
        base_url=DIGIFINEX_LIVE_HTTP_BASE_URL,
        opener=_opener,
    )
    payload = await client.request(
        "GET",
        "/public/instrument",
        params={"instrument_id": raw_symbol},
    )
    ts_init = time.time_ns()
    instrument = instrument_from_digifinex(payload, ts_init)
    if instrument.id != instrument_id:
        raise RuntimeError(
            f"DigiFinex instrument {raw_symbol} resolved to {instrument.id}, not {instrument_id}",
        )

    first_close_ns, last_close_ns = canonical_close_window(start, end, interval_ns)
    catalog = ParquetDataCatalog(str(catalog_path))
    existing = {bar.ts_event for bar in catalog.bars(bar_types=[market.bar_type])}
    wanted = set(range(first_close_ns, last_close_ns + interval_ns, interval_ns)) - existing
    collected: dict[int, Any] = {}
    if wanted:
        report_progress("downloading_data", f"下载 DigiFinex 行情 {market.instrument_id}")
        bars = await request_digifinex_bars_paginated(
            client,
            bar_type=bar_type,
            start=_moment(min(wanted)),
            end=_moment(max(wanted)),
            limit=0,
            ts_init=ts_init,
            instrument=instrument,
        )
        for bar in bars:
            if bar.ts_event in wanted and bar.ts_event not in collected:
                collected[bar.ts_event] = bar
        missing = sorted(wanted - set(collected))
        if missing:
            raise ValueError(
                f"DigiFinex returned incomplete {market.bar_type} data: {len(missing)} of "
                f"{len(wanted)} bars missing between {_moment(missing[0]).isoformat()} "
                f"and {_moment(missing[-1]).isoformat()}",
            )

    catalog.write_data([instrument])
    if collected:
        write_contiguous(catalog, list(collected.values()), interval_ns)
    verify_window(catalog, market.bar_type, VENUE, first_close_ns, last_close_ns, start, end)
    report_progress("downloading_data", f"DigiFinex 行情完成 {market.instrument_id}", 1, 1)
