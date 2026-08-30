"""Reviewed OKX public bars.

Two OKX behaviours drive this module, both measured against the live public
endpoint rather than assumed:

* OKX stamps a candle at its **opening** time, unlike Nautilus's Binance path
  which returns close-stamped klines. Research replays a completed external bar
  at its close, so every OKX bar is shifted forward by exactly one interval.
* A candle page is capped at 100 rows whatever limit is requested, and a page
  costs the same regardless of how many rows it carries because the time is
  round-trip latency. Long periods therefore need many requests, issued with a
  small bounded concurrency; past four the native client stops going faster.

The requests are public: no credential is read, and the placeholder below only
stops the native constructor from resolving one from the environment.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from ._common import (
    canonical_close_window,
    external_bar_interval_ns,
    https_proxy_url,
    report_progress,
    verify_window,
    write_contiguous,
)

UTC = timezone.utc
VENUE = "OKX"
PLACEHOLDER_CREDENTIAL = "PUBLIC_DATA_ONLY"
PAGE_SPAN = 90
PAGE_CONCURRENCY = 4


def unsupported_reason(market: Any, settings: dict[str, Any]) -> str | None:
    if market.data_type != "bars":
        return f"automatic Research download supports bars only, not {VENUE} {market.data_type}"
    if not settings.get("instrument_types"):
        # OKX's adapter defaults to spot, so a derivatives preset that omits this
        # key would otherwise fail deep inside the client with "did not return
        # <instrument>". Name the missing key rather than inferring it from the
        # symbol: the preset is the reviewed input.
        return (
            "OKX Research download requires instrument_types in the preset venue settings "
            f'(for example "instrument_types": ["SWAP"] for {market.instrument_id})'
        )
    return None


def _instrument_types(settings: dict[str, Any]) -> list[Any]:
    """Resolve preset strings to native enum members the way Live does.

    Presets carry ``"SWAP"`` while the native enum variant is ``Swap``, so the
    upper-case attribute lookup has to come first; matching Live's order keeps
    one preset valid in both products.
    """
    from nautilus_trader.core import nautilus_pyo3

    values = settings.get("instrument_types") or ()
    if isinstance(values, str):
        values = (values,)
    resolved = []
    for value in values:
        member = getattr(nautilus_pyo3.OKXInstrumentType, str(value).upper(), None)
        if member is None:
            try:
                member = nautilus_pyo3.OKXInstrumentType.from_str(str(value))
            except Exception as error:  # the native enum raises its own error type
                raise ValueError(f"unsupported OKX instrument_types entry: {value!r}") from error
        resolved.append(member)
    return resolved


def _pages(open_first_ns: int, open_last_ns: int, interval_ns: int) -> list[tuple[int, int]]:
    """Split an open-time range into pages that stay under OKX's 100-row cap."""
    pages = []
    cursor = open_first_ns
    while cursor <= open_last_ns:
        last = min(open_last_ns, cursor + (PAGE_SPAN - 1) * interval_ns)
        pages.append((cursor, last))
        cursor = last + interval_ns
    return pages


def _moment(nanoseconds: int) -> datetime:
    return datetime.fromtimestamp(nanoseconds / 1_000_000_000, UTC)


async def _fetch_pages(
    client: Any,
    native_bar_type: Any,
    pages: list[tuple[int, int]],
    interval_ns: int,
) -> list[Any]:
    """Fetch every page with bounded concurrency, reporting completion as it goes."""
    from nautilus_trader.model.data import Bar

    semaphore = asyncio.Semaphore(PAGE_CONCURRENCY)
    interval = timedelta(seconds=interval_ns / 1_000_000_000)
    completed = 0
    total = len(pages)

    async def fetch(first_ns: int, last_ns: int) -> list[Any]:
        nonlocal completed
        async with semaphore:
            # One interval of padding on each side absorbs the endpoint's
            # boundary handling; the caller filters to the exact window anyway.
            native = await client.request_bars(
                bar_type=native_bar_type,
                start=_moment(first_ns) - interval,
                end=_moment(last_ns) + interval + interval,
                limit=100,
            )
        completed += 1
        report_progress("downloading_data", f"下载 OKX 行情 {completed}/{total}", completed, total)
        return Bar.from_pyo3_list(native)

    results = await asyncio.gather(*(fetch(first, last) for first, last in pages))
    return [bar for page in results for bar in page]


async def download(
    catalog_path: Path,
    market: Any,
    settings: dict[str, Any],
    start: datetime,
    end: datetime,
) -> None:
    from nautilus_trader.adapters.okx.factories import get_cached_okx_http_client
    from nautilus_trader.core import nautilus_pyo3
    from nautilus_trader.model.data import Bar
    from nautilus_trader.model.instruments import instruments_from_pyo3
    from nautilus_trader.persistence.catalog import ParquetDataCatalog

    instrument_id = market.instrument_id
    bar_type = market.bar_type
    interval_ns = external_bar_interval_ns(bar_type, VENUE)
    client = get_cached_okx_http_client(
        api_key=PLACEHOLDER_CREDENTIAL,
        api_secret=PLACEHOLDER_CREDENTIAL,
        api_passphrase=PLACEHOLDER_CREDENTIAL,
        proxy_url=https_proxy_url(),
    )

    native_instruments = []
    for instrument_type in _instrument_types(settings):
        instruments, _ = await client.request_instruments(instrument_type, None)
        native_instruments.extend(instruments)
    target = next((item for item in native_instruments if str(item.id) == instrument_id), None)
    if target is None:
        raise ValueError(f"OKX did not return instrument {instrument_id}")
    client.cache_instrument(target)

    first_close_ns, last_close_ns = canonical_close_window(start, end, interval_ns)
    native_bar_type = nautilus_pyo3.BarType.from_str(bar_type)
    catalog = ParquetDataCatalog(str(catalog_path))
    existing = {bar.ts_event for bar in catalog.bars(bar_types=[bar_type])}
    wanted = set(range(first_close_ns, last_close_ns + interval_ns, interval_ns)) - existing
    collected: dict[int, Any] = {}

    def absorb(bars: list[Any]) -> None:
        for bar in bars:
            close_ns = bar.ts_event + interval_ns  # OKX stamps the opening time
            if close_ns not in wanted or close_ns in collected:
                continue
            values = Bar.to_dict(bar)
            values["ts_event"] = values["ts_init"] = close_ns
            collected[close_ns] = Bar.from_dict(values)

    if wanted:
        pages = _pages(first_close_ns - interval_ns, last_close_ns - interval_ns, interval_ns)
        absorb(await _fetch_pages(client, native_bar_type, pages, interval_ns))
        missing = sorted(wanted - set(collected))
        if missing:
            # One targeted retry over the gap: a single dropped page out of a
            # thousand would otherwise discard the whole period.
            retry = _pages(missing[0] - interval_ns, missing[-1] - interval_ns, interval_ns)
            absorb(await _fetch_pages(client, native_bar_type, retry, interval_ns))
            missing = sorted(wanted - set(collected))
        if missing:
            raise ValueError(
                f"OKX returned incomplete {bar_type} data: {len(missing)} of {len(wanted)} bars "
                f"missing between {_moment(missing[0]).isoformat()} and {_moment(missing[-1]).isoformat()}",
            )

    catalog.write_data([instruments_from_pyo3([target])[0]])
    if collected:
        write_contiguous(catalog, list(collected.values()), interval_ns)
    verify_window(catalog, bar_type, VENUE, first_close_ns, last_close_ns, start, end)
