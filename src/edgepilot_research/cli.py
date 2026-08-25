from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from . import __version__
from .marketplace import ResearchDownloadError, ResearchDownloadQuotaError, inspect, install, search, versions
from .paths import state_root
from .runtime import repair_runtime, runtime_status, uninstall_runtime
from .ui import serve, stop_dashboard


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(prog="edgepilot-research", description="Public strategy research and reproducible backtesting")
    root.add_argument("--version", action="version", version=__version__); commands = root.add_subparsers(dest="command", required=True)
    local = commands.add_parser("strategies"); local.add_argument("action", choices=["list", "inspect", "presets", "remove"], nargs="?", default="list"); local.add_argument("name", nargs="?")
    market = commands.add_parser("marketplace"); market.add_argument("action", choices=["search", "inspect", "versions", "install"]); market.add_argument("slug_or_query", nargs="?", default=""); market.add_argument("--version")
    backtest = commands.add_parser("backtest"); backtest.add_argument("strategy"); backtest.add_argument("--version", required=True); backtest.add_argument("--preset"); backtest.add_argument("--days", type=int, choices=[90, 365], default=90)
    runs = commands.add_parser("runs"); runs.add_argument("action", choices=["list", "show"], nargs="?", default="list"); runs.add_argument("run_id", nargs="?")
    data = commands.add_parser("data"); data.add_argument("action", choices=["import"]); data.add_argument("--strategy", required=True); data.add_argument("--version", required=True); data.add_argument("--market", required=True, type=int); data.add_argument("--csv", required=True, type=Path); data.add_argument("--instrument-json", required=True, type=Path)
    runtime = commands.add_parser("runtime"); runtime.add_argument("action", choices=["status", "repair", "uninstall"]); runtime.add_argument("--break-install-lock", action="store_true"); runtime.add_argument("--yes", action="store_true")
    ui = commands.add_parser("ui"); ui.add_argument("--host", default="127.0.0.1"); ui.add_argument("--port", type=int, default=8686); ui.add_argument("--stop", action="store_true")
    return root


def main(argv: list[str] | None = None) -> int:
    args = parser().parse_args(argv)
    try:
        if args.command == "strategies":
            from .engine import strategies
            if args.action == "list": print("\n".join(strategies()))
            else:
                if not args.name: raise ValueError("strategy name is required")
                target = state_root() / "strategies" / args.name
                if args.action == "remove":
                    if not target.is_dir(): raise ValueError(f"Strategy is not installed: {args.name}")
                    shutil.rmtree(target); print(json.dumps({"removed": args.name}))
                elif not target.is_dir(): raise ValueError(f"Strategy is not installed: {args.name}")
                elif args.action == "presets":
                    presets = target / "configs"; print("\n".join(path.stem for path in sorted(presets.glob("*.json"))) if presets.exists() else "")
                else:
                    metadata = target / "marketplace.json"; print(metadata.read_text(encoding="utf-8") if metadata.exists() else json.dumps({"name": args.name}))
        elif args.command == "backtest":
            from .engine import run
            print(json.dumps(run(args.strategy, args.version, args.preset, args.days), indent=2))
        elif args.command == "marketplace":
            if args.action == "search": value = search(args.slug_or_query)
            elif args.action == "versions": value = versions(args.slug_or_query)
            else:
                if not args.version: raise ValueError("--version is required")
                value = {"installed": str(install(args.slug_or_query, args.version))} if args.action == "install" else inspect(args.slug_or_query, args.version)
            print(json.dumps(value, ensure_ascii=False, indent=2))
        elif args.command == "runs":
            root = state_root() / "runs"
            if args.action == "list": print("\n".join(sorted((path.name for path in root.iterdir()), reverse=True)) if root.exists() else "")
            else:
                if not args.run_id: raise ValueError("run_id is required")
                print((root / args.run_id / "run.json").read_text(encoding="utf-8"))
        elif args.command == "data":
            from .data import import_bars
            print(json.dumps(import_bars(args.strategy, args.version, args.market, args.csv, args.instrument_json), indent=2))
        elif args.command == "runtime":
            if args.action == "status": value = runtime_status()
            elif args.action == "repair": value = repair_runtime(break_install_lock=args.break_install_lock)
            else: value = uninstall_runtime(accept=args.yes)
            print(json.dumps(value, indent=2))
        elif args.command == "ui":
            if args.stop: print(json.dumps(stop_dashboard(), indent=2))
            else: serve(args.host, args.port)
        return 0
    except ResearchDownloadError as error:
        payload: dict[str, object] = {
            "code": error.code,
            "message": "当前来源网络下载额度已用尽"
            if isinstance(error, ResearchDownloadQuotaError)
            else "Research strategy download is rate limited"
            if error.code == "RATE_LIMITED"
            else "Research strategy download is temporarily unavailable",
            "retryable": error.retryable,
        }
        if error.retry_after is not None:
            payload["retry_after"] = error.retry_after
        if isinstance(error, ResearchDownloadQuotaError):
            payload.update(
                limiting_scopes=error.limiting_scopes,
                quotas=error.quotas,
            )
        if error.request_id is not None:
            payload["request_id"] = error.request_id
        print(json.dumps({"error": payload}, ensure_ascii=False), file=sys.stderr)
        return 1
    except (OSError, ValueError) as error:
        print(f"error: {error}")
        return 1


if __name__ == "__main__": raise SystemExit(main())
