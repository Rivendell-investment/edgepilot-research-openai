"""Strict local market-data import facade for the shared Nautilus core."""

from __future__ import annotations

import csv
import json
import tempfile
import shutil
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from .paths import state_root

CSV_FIELDS = ["timestamp", "open", "high", "low", "close", "volume"]


def import_bars(strategy: str, version: str, market: int, csv_path: Path, instrument_json: Path) -> dict[str, Any]:
    if market < 0:
        raise ValueError("--market must be a zero-based non-negative index")
    strategy_root = _installed_strategy(strategy, version)
    instrument = _read_instrument(instrument_json)
    rows = validate_bars_csv(csv_path)
    preset_name = _benchmark_preset(strategy_root)
    preset = json.loads((strategy_root / "configs" / f"{preset_name}.json").read_text(encoding="utf-8"))
    markets = preset.get("backtest", {}).get("markets", []) if isinstance(preset, dict) else []
    if market >= len(markets) or not isinstance(markets[market], dict):
        raise ValueError(f"preset {preset_name!r} does not contain market index {market}")
    market_value = markets[market]
    result = _write_nautilus_catalog(rows, instrument, str(market_value.get("instrument_id", "")), str(market_value.get("bar_type", "")))
    return {**result, "validated_rows": len(rows), "preset": preset_name}


def validate_bars_csv(path: Path) -> list[tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal]]:
    try:
        source = path.open(newline="", encoding="utf-8")
    except OSError as error:
        raise ValueError(f"cannot open CSV: {error}") from error
    rows: list[tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal]] = []
    previous: datetime | None = None
    with source:
        reader = csv.DictReader(source)
        if reader.fieldnames != CSV_FIELDS:
            raise ValueError(f"CSV header must be exactly {','.join(CSV_FIELDS)}")
        for line, row in enumerate(reader, 2):
            stamp = str(row["timestamp"])
            try:
                parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00"))
            except ValueError as error:
                raise ValueError(f"CSV line {line} timestamp must be RFC3339") from error
            if parsed.tzinfo is None or parsed.utcoffset() is None or parsed.utcoffset().total_seconds() != 0:
                raise ValueError(f"CSV line {line} timestamp must be UTC")
            if previous is not None and parsed <= previous:
                raise ValueError(f"CSV line {line} timestamps must strictly increase")
            previous = parsed
            try:
                values = tuple(Decimal(str(row[name])) for name in CSV_FIELDS[1:])
            except InvalidOperation as error:
                raise ValueError(f"CSV line {line} contains an invalid decimal") from error
            if any(not value.is_finite() or value < 0 for value in values):
                raise ValueError(f"CSV line {line} values must be finite and non-negative")
            open_, high, low, close, volume = values
            if low > min(open_, close) or high < max(open_, close) or low > high:
                raise ValueError(f"CSV line {line} has invalid OHLC relationships")
            rows.append((stamp, open_, high, low, close, volume))
    if not rows:
        raise ValueError("CSV contains no bars")
    return rows


def _installed_strategy(slug: str, version: str) -> Path:
    root = state_root() / "strategies" / slug.replace("-", "_")
    metadata = root / ".edgepilot-install.json"
    if not metadata.is_file():
        raise ValueError(f"strategy is not installed with verified metadata: {slug}")
    value = json.loads(metadata.read_text(encoding="utf-8"))
    if value.get("slug") != slug or value.get("version") != version:
        raise ValueError(f"installed strategy version does not match {slug} {version}")
    return root


def _benchmark_preset(root: Path) -> str:
    value = json.loads((root / "marketplace.json").read_text(encoding="utf-8"))
    benchmark = value.get("benchmark")
    preset = benchmark.get("preset") if isinstance(benchmark, dict) else None
    return preset if isinstance(preset, str) and preset else "default"


def _read_instrument(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"instrument JSON is invalid: {error}") from error
    if not isinstance(value, dict) or not value:
        raise ValueError("instrument JSON must be a non-empty object")
    return value


def _write_nautilus_catalog(rows: list[tuple[str, Decimal, Decimal, Decimal, Decimal, Decimal]], instrument_value: dict[str, Any], instrument_id: str, bar_type: str) -> dict[str, Any]:
    try:
        from nautilus_trader.model import instruments
        from nautilus_trader.model.data import Bar
        from nautilus_trader.persistence.catalog import ParquetDataCatalog
    except ImportError as error:
        raise ValueError("Research runtime is incomplete: NautilusTrader is unavailable") from error
    type_name = instrument_value.get("type")
    instrument_class = getattr(instruments, str(type_name), None)
    if instrument_class is None or not callable(getattr(instrument_class, "from_dict", None)):
        raise ValueError("instrument JSON type is not supported by NautilusTrader")
    instrument = instrument_class.from_dict(instrument_value)
    if str(instrument.id) != instrument_id:
        raise ValueError("instrument JSON id differs from selected preset market")
    bars = []
    for stamp, open_, high, low, close, volume in rows:
        nanoseconds = int(datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp() * 1_000_000_000)
        prices = [format(value, f".{instrument.price_precision}f") for value in (open_, high, low, close)]
        sized_volume = format(volume, f".{instrument.size_precision}f")
        bars.append(Bar.from_dict({"type": "Bar", "bar_type": bar_type, "open": prices[0], "high": prices[1], "low": prices[2], "close": prices[3], "volume": sized_volume, "ts_event": nanoseconds, "ts_init": nanoseconds}))
    state = state_root()
    target = state / "catalog"
    state.mkdir(parents=True, exist_ok=True)
    import_lock = state / ".catalog-import.lock"
    try:
        import_lock.mkdir()
    except FileExistsError as error:
        raise ValueError("another catalog import is already running") from error
    staging_path = Path(tempfile.mkdtemp(prefix=".catalog-staging-", dir=state))
    backup = state / f".catalog-previous-{staging_path.name.removeprefix('.catalog-staging-')}"
    try:
        if target.exists():
            shutil.copytree(target, staging_path, dirs_exist_ok=True)
        staging = ParquetDataCatalog(str(staging_path))
        staging.write_data([instrument])
        staging.write_data(bars)
        imported = staging.bars(bar_types=[bar_type])
        imported_events = {bar.ts_event for bar in imported}
        if not all(bar.ts_event in imported_events for bar in bars):
            raise ValueError("temporary Nautilus catalog verification failed")
        if backup.exists():
            shutil.rmtree(backup)
        if target.exists():
            target.rename(backup)
        staging_path.rename(target)
        if backup.exists():
            shutil.rmtree(backup)
    except Exception:
        if not target.exists() and backup.exists():
            backup.rename(target)
        raise
    finally:
        if staging_path.exists():
            shutil.rmtree(staging_path)
        if backup.exists() and target.exists():
            shutil.rmtree(backup)
        import_lock.rmdir()
    return {"instrument_id": instrument_id, "bar_type": bar_type, "start": rows[0][0], "end": rows[-1][0], "catalog": str(target)}
