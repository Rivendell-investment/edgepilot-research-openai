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
        from edgepilot_backtest_core.discovery import resolve_strategy
        from edgepilot_backtest_core.models import BacktestRequest, MarketRequest, VenueRequest
        from edgepilot_backtest_core.presets import preset_backtest_values, preset_markets, preset_strategy_values, preset_venues
        from edgepilot_backtest_core.research import run_backtest
        from .reporting import export_reports
    except ImportError as error:
        raise ValueError("RUNTIME_INCOMPLETE: edgepilot-backtest-core or a locked dependency is unavailable") from error
    preset_value = json.loads(preset_path.read_text(encoding="utf-8"))
    if not isinstance(preset_value, dict):
        raise ValueError("strategy preset must contain an object")
    backtest = preset_backtest_values(preset_value)
    markets = tuple(MarketRequest(**market) for market in preset_markets(preset_value))
    venue_values = preset_venues(preset_value)
    venues = tuple(VenueRequest(name=name, **{key: value for key, value in values.items() if key != "adapter_options"}) for name, values in venue_values.items())
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
        from edgepilot_backtest_core import __version__
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
            start_ns = int(start.timestamp() * 1_000_000_000)
            end_ns = int(end.timestamp() * 1_000_000_000)
            missing = []
            for index, market in enumerate(markets):
                bars = catalog.bars(bar_types=[market.bar_type])
                interval_ns = int(BarType.from_str(market.bar_type).spec.timedelta.total_seconds() * 1_000_000_000)
                if (
                    not catalog.instruments(instrument_ids=[market.instrument_id])
                    or not bars
                    or min(bar.ts_event for bar in bars) > start_ns + interval_ns
                    or max(bar.ts_event for bar in bars) < end_ns
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
