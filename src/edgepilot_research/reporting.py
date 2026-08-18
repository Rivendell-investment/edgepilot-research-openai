from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from nautilus_trader.model.data import BarType
from nautilus_trader.persistence.catalog import ParquetDataCatalog


def export_reports(engine: Any, run_dir: Path, metrics: dict[str, Any], *, catalog_path: Path, bar_types: list[str], start: Any, end: Any, starting_balance: float) -> None:
    """Export the stable, dependency-light Research artifact contract."""
    run_dir.mkdir(parents=True, exist_ok=True)
    fills = engine.trader.generate_order_fills_report().reset_index()
    positions = engine.trader.generate_positions_report().reset_index()
    fills.to_csv(run_dir / "fills.csv", index=False)
    positions.to_csv(run_dir / "positions.csv", index=False)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, default=str) + "\n", encoding="utf-8")
    catalog = ParquetDataCatalog(str(catalog_path))
    start_ns, end_ns = int(start.timestamp() * 1_000_000_000), int(end.timestamp() * 1_000_000_000)
    market_series = []
    for bar_type in bar_types:
        instrument_id = str(BarType.from_str(bar_type).instrument_id)
        bars = [bar for bar in catalog.bars(bar_types=[bar_type]) if start_ns <= bar.ts_event <= end_ns]
        instruments = catalog.instruments(instrument_ids=[instrument_id])
        if not instruments:
            raise ValueError(f"instrument unavailable for report: {instrument_id}")
        market_positions = positions[positions.get("instrument_id", pd.Series(dtype=str)).astype(str).eq(instrument_id)]
        market_fills = fills[fills.get("instrument_id", pd.Series(dtype=str)).astype(str).eq(instrument_id)]
        market_series.append(_market_equity(bars, market_positions, market_fills, float(instruments[-1].multiplier)))
    timestamps = sorted({timestamp for frame in market_series for timestamp in frame["timestamp"]})
    series = pd.DataFrame({"timestamp": pd.to_datetime(timestamps, utc=True)})
    pnl = np.zeros(len(series), dtype=float)
    index = pd.DatetimeIndex(series["timestamp"])
    for frame in market_series:
        pnl += frame.set_index("timestamp")["pnl"].reindex(index, method="ffill").fillna(0.0).to_numpy(dtype=float)
    series["pnl"] = pnl
    series["equity"] = starting_balance + pnl
    peak = series["equity"].cummax()
    series["drawdown_pct"] = 100.0 * (series["equity"] / peak - 1.0)
    series.to_json(run_dir / "timeseries.json", orient="records", date_format="iso", indent=2)
    values = series["equity"].tolist()
    points = ""
    if values:
        low, high = min(values), max(values)
        scale = max(high - low, 1e-12)
        points = " ".join(f"{20 + index * 760 / max(1, len(values)-1):.1f},{180 - (value-low)*150/scale:.1f}" for index, value in enumerate(values))
    (run_dir / "equity.svg").write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="800" height="200" role="img" aria-label="Backtest equity curve"><rect width="100%" height="100%" fill="white"/><polyline fill="none" stroke="#176b4d" stroke-width="2" points="{points}"/></svg>\n', encoding="utf-8")


def _market_equity(bars: list[Any], positions: Any, fills: Any, multiplier: float) -> Any:
    frame = pd.DataFrame({
        "timestamp": [pd.Timestamp(bar.ts_event, unit="ns", tz="UTC") for bar in bars],
        "close": [bar.close.as_double() for bar in bars],
    }).sort_values("timestamp").reset_index(drop=True)
    timestamps = frame["timestamp"].astype("int64").to_numpy()
    prices = frame["close"].to_numpy(dtype=float)
    pnl = np.zeros(len(frame), dtype=float)
    opening_fees = {str(row["client_order_id"]): _money(row.get("commissions")) for _, row in fills.iterrows()}
    for _, position in positions.iterrows():
        opened, closed = pd.Timestamp(position["ts_opened"]).value, pd.Timestamp(position["ts_closed"]).value
        open_mask, closed_mask = (timestamps >= opened) & (timestamps < closed), timestamps >= closed
        direction = 1.0 if str(position["entry"]) == "BUY" else -1.0
        quantity, entry = float(position["peak_qty"]), float(position["avg_px_open"])
        pnl[open_mask] += direction * (prices[open_mask] - entry) * quantity * multiplier - opening_fees.get(str(position["opening_order_id"]), 0.0)
        pnl[closed_mask] += _money(position["realized_pnl"])
    frame["pnl"] = pnl
    return frame


def _money(value: Any) -> float:
    match = re.search(r"[-+]?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else 0.0
