# Data sources

Research backtests automatically download the selected 90-day or 365-day period
for reviewed Binance Futures bar markets using NautilusTrader's public HTTP
client. The downloader derives the instrument, bar type and account family only
from the installed preset, never accepts an arbitrary URL or reads API
credentials, and atomically preserves the previous catalog on failure. Other
venues and non-bar data remain unsupported. Users can alternatively import a
local CSV plus explicit Nautilus instrument metadata.

The CSV header is exactly
`timestamp,open,high,low,close,volume`. Timestamps are strictly increasing RFC3339
UTC values; prices and volume are finite non-negative decimals with valid OHLC
relationships. The instrument JSON must use a Nautilus-supported instrument
`type` and its instrument id must match the selected benchmark market. The
importer validates a temporary Parquet catalog before atomically replacing the
local catalog.

Before adding an online provider in a later release, confirm its license,
attribution, caching, retention and redistribution terms; record the exact
provider and dataset here; and add user-consent and failure-path tests. Until
those changes are reviewed, documentation and Skill instructions must not claim
that public market data is fetched automatically.
