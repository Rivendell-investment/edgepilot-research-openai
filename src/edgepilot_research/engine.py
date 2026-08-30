from __future__ import annotations

import json
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Any

from .data import _benchmark_preset, _installed_strategy
from .paths import state_root
from .runtime import require_active_runtime, runtime_status
from .public_data import ensure_public_data, research_period
from .public_data_venues import canonical_close_window as _canonical_close_window

VENUE_FIELDS = {
    "starting_balance",
    "base_currency",
    "account_type",
    "oms_type",
    "maker_fee_bps",
    "taker_fee_bps",
    "default_leverage",
    "leverages",
    "allow_cash_borrowing",
    "liquidation_enabled",
    "liquidation_trigger_ratio",
    "liquidation_cancel_open_orders",
    "adapter_options",
}


def strategies() -> list[str]:
    root = state_root() / "strategies"
    return sorted(path.name for path in root.iterdir() if path.is_dir()) if root.exists() else []


def run(
    strategy: str,
    version: str,
    preset: str | None = None,
    days: int = 90,
) -> dict[str, Any]:
    """Run an exact installed formal strategy through the shared Nautilus core."""
    require_active_runtime()
    strategy_root = _installed_strategy(strategy, version)
    selected = preset or _benchmark_preset(strategy_root)
    preset_path = strategy_root / "configs" / f"{selected}.json"
    if not preset_path.is_file():
        available = ", ".join(path.stem for path in sorted((strategy_root / "configs").glob("*.json")))
        raise ValueError(f"preset {selected!r} does not exist; available: {available or '(none)'}")
    try:
        from edgepilot_core.backtest.discovery import resolve_strategy
        from edgepilot_core.backtest.models import BacktestRequest, MarketRequest
        from edgepilot_core.backtest.presets import preset_backtest_values, preset_markets, preset_strategy_values, preset_venues
        from edgepilot_core.backtest.research import run_backtest
        from .reporting import export_reports
    except ImportError as error:
        raise ValueError("RUNTIME_INCOMPLETE: edgepilot-core or a locked dependency is unavailable") from error
    preset_value = json.loads(preset_path.read_text(encoding="utf-8"))
    if not isinstance(preset_value, dict):
        raise ValueError("strategy preset must contain an object")
    backtest = preset_backtest_values(preset_value)
    markets = tuple(MarketRequest(**market) for market in preset_markets(preset_value))
    venue_values = preset_venues(preset_value)
    venues = _venue_requests(venue_values)
    start, end = research_period(days, markets)
    request = BacktestRequest(
        strategy=resolve_strategy(strategy_root.name, strategies_root=strategy_root.parent),
        markets=markets,
        venues=venues,
        start=start,
        end=end,
        parameters=preset_strategy_values(preset_value),
        catalog_path=state_root() / "catalog",
        runs_path=state_root() / "runs",
        preset_name=selected,
    )
    ensure_public_data(markets, venue_values, start, end)
    _require_catalog(request.catalog_path, markets, strategy, version, selected, start, end)
    run_id, metrics = run_backtest(request, report_exporter=export_reports)
    _attach_research_provenance(
        request.runs_path / run_id / "run.json",
        strategy_root=strategy_root,
        preset_path=preset_path,
        catalog_path=request.catalog_path,
    )
    result = {"run_id": run_id, "metrics": metrics, "strategy": strategy, "version": version, "preset": selected, "days": days}
    if not isinstance(metrics, dict):
        raise ValueError("backtest core returned an invalid result")
    return result


def _venue_requests(venue_values: dict[str, dict[str, Any]]) -> tuple[Any, ...]:
    from edgepilot_core.backtest.models import VenueRequest
    from edgepilot_core.backtest.presets import public_adapter_options

    venues = []
    for name, settings in venue_values.items():
        explicit_options = settings.get("adapter_options", {})
        if not isinstance(explicit_options, dict):
            raise TypeError(f"Venue adapter_options for {name} must be an object")
        venues.append(VenueRequest(
            name=name,
            adapter_options={
                **public_adapter_options({key: value for key, value in settings.items() if key not in VENUE_FIELDS}),
                **public_adapter_options(explicit_options),
            },
            starting_balance=float(settings.get("starting_balance", 100_000.0)),
            base_currency=str(settings.get("base_currency", "USDT")),
            account_type=str(settings.get("account_type", "MARGIN")),
            oms_type=str(settings.get("oms_type", "NETTING")),
            maker_fee_bps=settings.get("maker_fee_bps"),
            taker_fee_bps=settings.get("taker_fee_bps"),
            default_leverage=float(settings.get("default_leverage", 1.0)),
            leverages=settings.get("leverages"),
            allow_cash_borrowing=bool(settings.get("allow_cash_borrowing", False)),
            liquidation_enabled=bool(settings.get("liquidation_enabled", False)),
            liquidation_trigger_ratio=float(settings.get("liquidation_trigger_ratio", 1.0)),
            liquidation_cancel_open_orders=bool(settings.get("liquidation_cancel_open_orders", True)),
        ))
    return tuple(venues)


def _attach_research_provenance(run_path: Path, *, strategy_root: Path, preset_path: Path, catalog_path: Path) -> None:
    record = json.loads(run_path.read_text(encoding="utf-8"))
    install = json.loads((strategy_root / ".edgepilot-install.json").read_text(encoding="utf-8"))
    runtime = runtime_status()
    record["provenance"] = {
        "core_version": _core_version(),
        "plugin_content_digest": runtime.get("plugin_content_digest"),
        "runtime_id": runtime.get("runtime_id"),
        "runtime_lock_sha256": runtime.get("runtime_lock_sha256"),
        "wheelhouse_sha256": runtime.get("wheelhouse_sha256"),
        "strategy_package_sha256": install.get("package_sha256"),
        "preset_sha256": hashlib.sha256(preset_path.read_bytes()).hexdigest(),
        "catalog_sha256": _tree_digest(catalog_path),
    }
    run_path.write_text(json.dumps(record, indent=2, default=str) + "\n", encoding="utf-8")


def _tree_digest(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        relative = path.relative_to(root).as_posix().encode()
        digest.update(relative + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _core_version() -> str:
    try:
        from edgepilot_core import __version__
        return str(__version__)
    except (ImportError, AttributeError):
        return "unknown"


def _require_catalog(catalog_path: Path, markets: tuple[Any, ...], strategy: str, version: str, preset: str, start: datetime, end: datetime) -> None:
    if not catalog_path.exists():
        missing = list(range(len(markets)))
    else:
        try:
            from nautilus_trader.model.data import BarType
            from nautilus_trader.persistence.catalog import ParquetDataCatalog
            catalog = ParquetDataCatalog(str(catalog_path))
            missing = []
            for index, market in enumerate(markets):
                bars = catalog.bars(bar_types=[market.bar_type])
                interval_ns = int(BarType.from_str(market.bar_type).spec.timedelta.total_seconds() * 1_000_000_000)
                first_close_ns, last_close_ns = _canonical_close_window(start, end, interval_ns)
                available = {
                    bar.ts_event
                    for bar in bars
                    if first_close_ns <= bar.ts_event <= last_close_ns
                }
                if (
                    not catalog.instruments(instrument_ids=[market.instrument_id])
                    or any(
                        timestamp not in available
                        for timestamp in range(first_close_ns, last_close_ns + 1, interval_ns)
                    )
                ):
                    missing.append(index)
        except Exception as error:
            raise ValueError(f"CATALOG_READ_FAILED: cannot inspect {catalog_path}: {error}") from error
    if missing:
        lines = [
            "CATALOG_DATA_MISSING: the selected period is incomplete after public-data download or local import.",
            f"Expected catalog: {catalog_path}",
            f"Required period: {start.isoformat()} to {end.isoformat()}",
            "CSV header: timestamp,open,high,low,close,volume",
        ]
        for index in missing:
            market = markets[index]
            lines.extend([
                f"Required instrument: {market.instrument_id}",
                f"Required bar type: {market.bar_type}",
                "Import command: "
                f"edgepilot-research data import --strategy {strategy} --version {version} --market {index} "
                "--csv <bars.csv> --instrument-json <instrument.json>",
            ])
        raise ValueError("\n".join(lines))


def installed_metadata(strategy: str) -> dict[str, Any]:
    root = state_root() / "strategies" / strategy.replace("-", "_")
    metadata = root / ".edgepilot-install.json"
    if not metadata.is_file():
        raise ValueError(f"strategy is not installed: {strategy}")
    return json.loads(metadata.read_text(encoding="utf-8"))
