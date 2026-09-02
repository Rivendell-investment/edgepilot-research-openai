# Data sources

Research backtests automatically download the selected 90-day or 365-day period
for reviewed public bar markets using NautilusTrader's native HTTP clients. The
downloader derives the venue, instrument, bar type and venue settings only from
the installed preset, never accepts an arbitrary URL or reads API credentials,
and atomically preserves the previous catalog on failure. A venue without an
entry below, and any non-bar data type, remains unsupported and fails with
`PUBLIC_DATA_UNSUPPORTED`. Users can alternatively import a local CSV plus
explicit Nautilus instrument metadata.

Each reviewed venue is one module under
`src/edgepilot_research/public_data_venues/`, listed in an explicit registry in
that package's `__init__.py`. The registry is a literal table rather than a
dynamic import so that the set of venues Research reaches can be audited by
reading one file.

## Reviewed venues

### Binance Futures

| | |
|---|---|
| Provider | Binance USD-M / COIN-M Futures public market data |
| Endpoint | `fapi`/`dapi` public klines, via NautilusTrader's Binance HTTP client |
| Authentication | None. The client is constructed with `api_key=None`, `api_secret=None` |
| Preset requirement | `account_type` must be `USDT_FUTURES` or `COIN_FUTURES` |
| Page size | 1000 bars per request |
| Timestamp | Nautilus returns completed klines stamped at their **close**; the request window is mapped back to Binance open times |

### OKX

| | |
|---|---|
| Provider | OKX public market data |
| Endpoint | `/api/v5/public/instruments` and the historical candles endpoint, via NautilusTrader's native OKX HTTP client |
| Authentication | None. The client receives the literal placeholder `PUBLIC_DATA_ONLY` for key, secret and passphrase purely to stop the native constructor from resolving real credentials out of the environment; these endpoints do not authenticate the request |
| Preset requirement | `instrument_types` must be declared (for example `["SWAP"]`). The OKX adapter defaults to spot, so a derivatives preset that omits it cannot resolve its instrument |
| Page size | **100 bars per request, capped by the venue** — a larger requested limit is ignored. Pages are fetched with a bounded concurrency of 4; beyond that the native client stops going faster |
| Timestamp | OKX stamps a candle at its **opening** time. Research replays a completed external bar at its close, so every OKX bar is shifted forward by exactly one interval before it is written |

The OKX opening-time behaviour was verified against
`/api/v5/market/history-candles` directly: the raw candle stamped `06:00` carries
the close of the 06:00–07:00 period, and the native client passes that same
stamp through. Getting this wrong would place the whole series one interval
early and surface as a misleading "data missing" error rather than a timestamp
fault, so a provider for a new venue must establish this before it ships.

### DigiFinex Swap

| | |
|---|---|
| Provider | DigiFinex Swap perpetual public market data |
| Endpoint | `/public/instrument` and `/public/candles_history`, via NautilusTrader's DigiFinex HTTP client |
| Authentication | None. Research passes no API key or secret and never initializes an execution client |
| Preset requirement | A DigiFinex Swap perpetual instrument and a time-aggregated `-LAST-EXTERNAL` bar type; no venue credentials or extra settings |
| Page size | 100 candles per request (the native client caps and advances ascending pages) |
| Timestamp | The native parser preserves DigiFinex's millisecond candle timestamp as the canonical completed-bar timestamp |
| Endpoint environment | Always the production `https://openapi.digifinex.com/swap/v2` host; the VPN-only DigiFinex Test host is never selected by Research |

The Live catalog downloader applies the same LIVE default when a DigiFinex
environment is omitted. Explicit `TEST` remains available only for controlled
demo/test execution or an explicitly requested test download.

## Local retention and redistribution

Downloaded bars are written to the Nautilus Parquet catalog under the Research
state root on the user's own machine. They stay there until the user deletes
them, are never uploaded to EdgePilot or any third party, and Research does not
redistribute venue market data: each installation fetches directly from the
venue. Only the public endpoints named above are contacted; no order, account or
credential endpoint is reachable from this code path.

> **Outstanding for each venue above:** the commercial terms — licence,
> attribution obligations, caching and redistribution permissions in the venue's
> API terms of service — are a legal review, not an engineering one, and are not
> asserted here. Record the confirmed terms in this section before treating a
> venue as cleared for release.

## CSV import

The CSV header is exactly
`timestamp,open,high,low,close,volume`. Timestamps are strictly increasing RFC3339
UTC values; prices and volume are finite non-negative decimals with valid OHLC
relationships. The instrument JSON must use a Nautilus-supported instrument
`type` and its instrument id must match the selected benchmark market. The
importer validates a temporary Parquet catalog before atomically replacing the
local catalog.

## Adding a venue

Write the module, establish its timestamp convention and page limit against the
live endpoint, record both in this file with the commercial terms, add one line
to the registry, and add failure-path tests. Until those changes are reviewed,
documentation and Skill instructions must not claim that the venue's public
market data is fetched automatically.
