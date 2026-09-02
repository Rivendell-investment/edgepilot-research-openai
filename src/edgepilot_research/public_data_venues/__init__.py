"""Reviewed public market-data providers, one module per venue.

The registry is an explicit table on purpose. ``DATA_SOURCES.md`` requires every
online provider to be reviewed and recorded before it ships, and importing a
module by venue name would make "which venues can Research reach" impossible to
audit by reading this file.

Adding a venue is: write the module, review and record it in ``DATA_SOURCES.md``,
add one line here.
"""

from __future__ import annotations

from types import ModuleType

from . import binance, digifinex, okx
from ._common import PROGRESS_PREFIX, canonical_close_window

PROVIDERS: dict[str, ModuleType] = {
    "BINANCE": binance,
    "DIGIFINEX": digifinex,
    "OKX": okx,
}

__all__ = ["PROGRESS_PREFIX", "PROVIDERS", "canonical_close_window", "provider_for", "supported_venues"]


def supported_venues() -> tuple[str, ...]:
    return tuple(sorted(PROVIDERS))


def provider_for(venue: str) -> ModuleType | None:
    return PROVIDERS.get(venue.upper())
