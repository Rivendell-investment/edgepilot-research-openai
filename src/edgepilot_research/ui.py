"""Loopback-only Research dashboard and its narrow local JSON API."""

from __future__ import annotations

import http.client
import json
import logging
import mimetypes
import os
import re
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Lock, Thread
from typing import Any, Callable, cast
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from .marketplace import DigestMismatchError, IDENTIFIER, InstallConflictError, RECOMMENDATION_FIELDS, ResearchDownloadError, ResearchDownloadQuotaError, ResearchRecommendationError, VERSION, inspect, install, recommend, search, versions
from .paths import state_root
from .process import pid_exists as _pid_exists
from .runtime import active_runtime_python, install_runtime, runtime_install_info, runtime_status

ASSETS = Path(__file__).with_name("ui_assets") / "app"
LOCALES = ("en", "ko", "zh-CN", "zh-TW")
RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
JOB_ID = re.compile(r"^[A-Za-z0-9_-]{20,80}$")
ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b[@-Z\\-_]")
MAX_BODY = 16 * 1024
MAX_JSON_FILE = 8 * 1024 * 1024
MAX_TIMESERIES_JSON_FILE = 64 * 1024 * 1024
MAX_TIMESERIES_POINTS = 2_000
JOBS: dict[str, dict[str, Any]] = {}
JOBS_LOCK = Lock()
LOGGER = logging.getLogger("edgepilot_research.ui")
DASHBOARD_RECORD = "dashboard.json"
DASHBOARD_LOCK = "dashboard.lock"
DASHBOARD_FIELDS = {"schema_version", "pid", "instance_nonce", "host", "port", "started_at", "python_executable", "active_release", "runtime_id", "plugin_content_digest"}


class ConflictError(ValueError):
    """A safe local mutation conflicts with current state."""


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as output:
            json.dump(value, output, sort_keys=True, separators=(",", ":"))
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def _health_matches(record: dict[str, Any]) -> bool:
    try:
        value = _dashboard_request(record, "GET", "/api/health")
        return isinstance(value, dict) and all(value.get(key) == record.get(key) for key in DASHBOARD_FIELDS)
    except ConflictError:
        return False


def _dashboard_request(
    record: dict[str, Any],
    method: str,
    path: str,
    *,
    body: dict[str, Any] | None = None,
    csrf: str = "",
) -> dict[str, Any] | None:
    host, port, nonce = record.get("host"), record.get("port"), record.get("instance_nonce")
    if host not in {"127.0.0.1", "localhost", "::1"} or not isinstance(port, int) or not isinstance(nonce, str):
        return None
    connection: http.client.HTTPConnection | None = None
    try:
        connection = http.client.HTTPConnection(host, port, timeout=1)
        display = f"[{host}]" if ":" in host else host
        headers = {"Host": f"{display}:{port}"}
        payload: bytes | None = None
        if body is not None:
            payload = json.dumps(body, separators=(",", ":")).encode()
            headers.update({"Origin": f"http://{display}:{port}", "X-EdgePilot-CSRF": csrf, "Content-Type": "application/json"})
        connection.request(method, path, body=payload, headers=headers)
        response = connection.getresponse()
        value = json.loads(response.read())
        if response.status not in {200, 202}:
            message = value.get("error", {}).get("message") if isinstance(value, dict) else None
            raise ConflictError(str(message or f"Dashboard request failed ({response.status})"))
        return value if isinstance(value, dict) else None
    except ConflictError:
        raise
    except (OSError, ValueError, json.JSONDecodeError):
        return None
    finally:
        if connection is not None:
            connection.close()


def _dashboard_identity(host: str, port: int, nonce: str) -> dict[str, Any]:
    try:
        status = runtime_status()
    except ValueError:
        status = {"installed": False}
    return {
        "schema_version": 1,
        "pid": os.getpid(),
        "instance_nonce": nonce,
        "host": host,
        "port": port,
        "started_at": int(time.time()),
        "python_executable": str(Path(sys.executable).absolute()),
        "active_release": status.get("active_release"),
        "runtime_id": status.get("runtime_id"),
        "plugin_content_digest": status.get("plugin_content_digest"),
    }


def _read_dashboard_record(root: Path) -> dict[str, Any]:
    record = _read_json(root / DASHBOARD_RECORD)
    if not isinstance(record, dict) or set(record) != DASHBOARD_FIELDS:
        raise ValueError("RUNTIME_PROCESS_STALE: Dashboard instance record is invalid")
    if not isinstance(record["pid"], int) or not isinstance(record["port"], int) or record["host"] not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("RUNTIME_PROCESS_STALE: Dashboard instance identity is invalid")
    if not all(isinstance(record[key], str) for key in ("instance_nonce", "python_executable", "active_release", "runtime_id", "plugin_content_digest")):
        raise ValueError("RUNTIME_PROCESS_STALE: Dashboard runtime identity is invalid")
    return record


def stop_dashboard(*, home: Path | None = None, timeout: float = 10.0) -> dict[str, Any]:
    root = (home or state_root()).resolve()
    try:
        record = _read_dashboard_record(root)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        if isinstance(error, ValueError) and str(error).startswith("RUNTIME_PROCESS_STALE:"):
            raise
        raise ValueError("RUNTIME_PROCESS_STALE: no verifiable Dashboard instance is recorded") from error
    if not _pid_exists(record["pid"]) or not _health_matches(record):
        raise ValueError("RUNTIME_PROCESS_STALE: Dashboard record and health identity do not match")
    bootstrap = _dashboard_request(record, "GET", "/api/bootstrap")
    csrf = bootstrap.get("csrf_token") if isinstance(bootstrap, dict) else None
    if not isinstance(csrf, str) or not csrf:
        raise ValueError("RUNTIME_PROCESS_STALE: Dashboard CSRF bootstrap is unavailable")
    response = _dashboard_request(record, "POST", "/api/process/stop", body={"instance_nonce": record["instance_nonce"]}, csrf=csrf)
    if not isinstance(response, dict) or response.get("stopping") is not True:
        raise ValueError("DASHBOARD_RESTART_FAILED: Dashboard did not accept the stop request")
    deadline = time.monotonic() + timeout
    while _pid_exists(record["pid"]):
        if time.monotonic() >= deadline:
            raise ValueError("DASHBOARD_RESTART_FAILED: Dashboard did not stop before the timeout")
        time.sleep(0.05)
    return {"stopped": True, "host": record["host"], "port": record["port"], "instance_nonce": record["instance_nonce"]}


def _acquire_dashboard_lock(root: Path, nonce: str) -> Path:
    lock = root / DASHBOARD_LOCK
    record_path = root / DASHBOARD_RECORD
    root.mkdir(parents=True, exist_ok=True)
    try:
        lock.mkdir(mode=0o700)
    except FileExistsError:
        try:
            record = _read_json(record_path)
        except (OSError, ValueError, json.JSONDecodeError):
            record = {}
        try:
            owner = _read_json(lock / "owner.json")
        except (OSError, ValueError, json.JSONDecodeError):
            owner = {}
        pid = record.get("pid") if isinstance(record, dict) else None
        owner_pid = owner.get("pid") if isinstance(owner, dict) else None
        if (isinstance(owner_pid, int) and _pid_exists(owner_pid)) or (isinstance(pid, int) and _pid_exists(pid)):
            raise ConflictError("another Research Dashboard is already running")
        if isinstance(record, dict) and _health_matches(record):
            raise ConflictError("another Research Dashboard is already running")
        if not isinstance(owner_pid, int) and time.time() - lock.stat().st_mtime < 30:
            raise ConflictError("another Research Dashboard is starting")
        shutil.rmtree(lock)
        record_path.unlink(missing_ok=True)
        try:
            lock.mkdir(mode=0o700)
        except FileExistsError as error:
            raise ConflictError("another Research Dashboard is starting") from error
    _atomic_json(lock / "owner.json", {"pid": os.getpid(), "instance_nonce": nonce, "started_at": int(time.time())})
    return lock


def _release_dashboard_lock(root: Path, nonce: str) -> None:
    record_path = root / DASHBOARD_RECORD
    lock = root / DASHBOARD_LOCK
    try:
        record = _read_json(record_path)
        if isinstance(record, dict) and secrets.compare_digest(str(record.get("instance_nonce", "")), nonce):
            record_path.unlink(missing_ok=True)
    except (OSError, ValueError, json.JSONDecodeError):
        pass
    try:
        owner = _read_json(lock / "owner.json")
        if isinstance(owner, dict) and secrets.compare_digest(str(owner.get("instance_nonce", "")), nonce):
            shutil.rmtree(lock)
    except (OSError, ValueError, json.JSONDecodeError):
        pass


def _read_json(path: Path, *, maximum: int = 512 * 1024) -> Any:
    if not path.is_file() or path.stat().st_size > maximum:
        raise ValueError(f"invalid or oversized JSON artifact: {path.name}")
    value = json.loads(path.read_text(encoding="utf-8"))
    return value


def _locale(value: str) -> str:
    candidate = value.replace("_", "-").strip()
    lowered = candidate.lower()
    if lowered.startswith("ko"):
        return "ko"
    if lowered.startswith("zh"):
        return "zh-TW" if any(part in lowered for part in ("hant", "-tw", "-hk", "-mo")) else "zh-CN"
    return "en"


def _strategy_directory(slug: str) -> Path:
    if not IDENTIFIER.fullmatch(slug):
        raise ValueError("invalid strategy slug")
    return state_root() / "strategies" / slug.replace("-", "_")


def _safe_text(value: Any, maximum: int = 4096) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    if len(value.encode("utf-8")) > maximum or any(ord(char) < 32 and char not in "\t\n\r" for char in value):
        return ""
    return value


def _strategy_record(directory: Path, locale: str) -> dict[str, Any]:
    install_record = _read_json(directory / ".edgepilot-install.json")
    manifest = _read_json(directory / "marketplace.json")
    if not isinstance(install_record, dict) or not isinstance(manifest, dict):
        raise ValueError("strategy metadata must contain objects")
    slug, version = install_record.get("slug"), install_record.get("version")
    if not isinstance(slug, str) or not IDENTIFIER.fullmatch(slug) or not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("strategy install metadata has invalid identity")
    if directory != _strategy_directory(slug) or manifest.get("slug") != slug or manifest.get("version") != version:
        raise ValueError("strategy metadata identity is inconsistent")
    configs = directory / "configs"
    presets = sorted(path.stem for path in configs.glob("*.json") if path.is_file() and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", path.stem)) if configs.is_dir() else []
    if not presets:
        raise ValueError("strategy has no valid preset")
    benchmark = manifest.get("benchmark")
    benchmark_preset = benchmark.get("preset") if isinstance(benchmark, dict) else "default"
    if benchmark_preset not in presets:
        benchmark_preset = presets[0]
    translated: dict[str, Any] = {}
    translations = manifest.get("translations")
    if locale != "en" and isinstance(translations, dict) and isinstance(translations.get(locale), dict):
        translated = translations[locale]
    capacity = manifest.get("capacity") if isinstance(manifest.get("capacity"), dict) else {}
    markets = manifest.get("markets") if isinstance(manifest.get("markets"), dict) else {}
    assets_value = markets.get("assets")
    assets: list[Any] = assets_value if isinstance(assets_value, list) else []
    risk_profile = manifest.get("risk_profile")
    record = {
        "slug": slug,
        "version": version,
        "display_name": _safe_text(translated.get("name")) or _safe_text(manifest.get("name")) or slug,
        "summary": _safe_text(translated.get("summary")) or _safe_text(manifest.get("summary")),
        "description": _safe_text(translated.get("description"), 64 * 1024) or _safe_text(manifest.get("description"), 64 * 1024),
        "content_locale": locale if translated else "en",
        "presets": presets,
        "benchmark_preset": benchmark_preset,
        "package_sha256": install_record.get("package_sha256"),
        "risk_profile": risk_profile if risk_profile in {"conservative", "balanced", "aggressive"} else None,
        "capacity_usd": capacity.get("usd") if isinstance(capacity.get("usd"), (int, float)) else None,
        "assets": [value for value in assets if isinstance(value, str) and value][:20],
    }
    recent = run_records(slug)["runs"]
    record["recent_run"] = recent[0] if recent else None
    return record


def strategy_records(locale: str = "en") -> dict[str, Any]:
    root = state_root() / "strategies"
    strategies: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    if root.is_dir():
        for directory in sorted((path for path in root.iterdir() if path.is_dir()), key=lambda path: path.name):
            try:
                strategies.append(_strategy_record(directory, locale))
            except (OSError, ValueError, json.JSONDecodeError):
                diagnostics.append({"code": "INVALID_INSTALL", "entry": directory.name})
    strategies.sort(key=lambda item: (item["display_name"].casefold(), item["slug"]))
    return {"strategies": strategies, "diagnostics": diagnostics}


def _installed(slug: str) -> dict[str, Any]:
    for record in strategy_records("en")["strategies"]:
        if record["slug"] == slug:
            return record
    raise FileNotFoundError("strategy is not installed")


def _run_directories() -> list[Path]:
    root = state_root() / "runs"
    if not root.is_dir():
        return []
    return sorted((path for path in root.iterdir() if path.is_dir() and RUN_ID.fullmatch(path.name)), reverse=True)


def _run_summary(path: Path) -> dict[str, Any]:
    record = _read_json(path / "run.json")
    if not isinstance(record, dict):
        raise ValueError("run record must be an object")
    strategy = record.get("strategy") if isinstance(record.get("strategy"), dict) else {}
    return {
        "run_id": path.name,
        "strategy": strategy.get("name"),
        "preset": strategy.get("preset"),
        "period": record.get("period"),
        "metrics": record.get("metrics"),
        "provenance": record.get("provenance"),
    }


def run_records(slug: str = "") -> dict[str, Any]:
    if slug and not IDENTIFIER.fullmatch(slug):
        raise ValueError("invalid strategy slug")
    internal_name = slug.replace("-", "_") if slug else ""
    records: list[dict[str, Any]] = []
    diagnostics: list[dict[str, str]] = []
    for path in _run_directories():
        try:
            record = _run_summary(path)
            if not internal_name or record.get("strategy") == internal_name:
                records.append(record)
        except (OSError, ValueError, json.JSONDecodeError):
            diagnostics.append({"code": "INVALID_RUN", "run_id": path.name})
    return {"runs": records, "diagnostics": diagnostics}


def _downsample_timeseries(points: list[dict[str, Any]], maximum: int = MAX_TIMESERIES_POINTS) -> list[dict[str, Any]]:
    """Keep a deterministic overview while preserving endpoints and global extrema."""
    if len(points) <= maximum:
        return points
    required = {0, len(points) - 1}
    for field in ("equity", "drawdown_pct"):
        numeric = [(index, point.get(field)) for index, point in enumerate(points) if isinstance(point.get(field), (int, float))]
        if numeric:
            required.add(min(numeric, key=lambda item: item[1])[0])
            required.add(max(numeric, key=lambda item: item[1])[0])
    remaining = maximum - len(required)
    if remaining > 0:
        span = len(points) - 1
        required.update(round(index * span / (remaining + 1)) for index in range(1, remaining + 1))
    if len(required) < maximum:
        required.update(index for index in range(len(points)) if index not in required and len(required) < maximum)
    return [points[index] for index in sorted(required)[:maximum]]


def run_detail(run_id: str) -> dict[str, Any]:
    if not RUN_ID.fullmatch(run_id):
        raise ValueError("invalid run id")
    root = state_root() / "runs" / run_id
    if root not in _run_directories():
        raise FileNotFoundError("run not found")
    record = _read_json(root / "run.json", maximum=MAX_JSON_FILE)
    if not isinstance(record, dict):
        raise ValueError("run record must be an object")
    allowed = {key: record.get(key) for key in ("run_id", "mode", "strategy", "markets", "venues", "period", "metrics", "provenance")}
    timeseries: list[dict[str, Any]] = []
    timeseries_meta = {"original_points": 0, "returned_points": 0, "downsampled": False}
    timeseries_path = root / "timeseries.json"
    if timeseries_path.is_file():
        raw = _read_json(timeseries_path, maximum=MAX_TIMESERIES_JSON_FILE)
        if isinstance(raw, list):
            normalized = [{key: point.get(key) for key in ("timestamp", "equity", "drawdown_pct")} for point in raw if isinstance(point, dict)]
            timeseries = _downsample_timeseries(normalized)
            timeseries_meta = {"original_points": len(normalized), "returned_points": len(timeseries), "downsampled": len(timeseries) < len(normalized)}
    allowed["timeseries"] = timeseries
    allowed["timeseries_meta"] = timeseries_meta
    strategy = allowed.get("strategy") if isinstance(allowed.get("strategy"), dict) else {}
    internal_name = strategy.get("name")
    preset = strategy.get("preset")
    if isinstance(internal_name, str) and isinstance(preset, str):
        slug = internal_name.replace("_", "-")
        try:
            installed = _installed(slug)
            period = allowed.get("period") if isinstance(allowed.get("period"), dict) else {}
            start = datetime.fromisoformat(str(period.get("start")))
            end = datetime.fromisoformat(str(period.get("end")))
            days = (end - start).days
            if days not in {90, 365}:
                raise ValueError("run period is not reproducible by the public CLI")
            allowed["reproduction_command"] = (
                f"edgepilot-research backtest {slug} --version {installed['version']} --preset {preset} --days {days}"
            )
        except (FileNotFoundError, ValueError):
            allowed["reproduction_command"] = None
    else:
        allowed["reproduction_command"] = None
    return allowed


def _safe_runtime() -> dict[str, Any]:
    status = runtime_status()
    result = {key: status.get(key) for key in ("installed", "runtime_id", "plugin_content_digest", "runtime_lock_sha256", "wheelhouse_sha256", "active_release", "release_exists") if key in status}
    if status.get("installed"):
        root = Path(str(status["home"]))
        result["python_executable"] = str(Path(sys.executable).absolute())
        result["process_current"] = Path(sys.prefix).resolve() == (root / str(status["active_release"]) / ".venv").resolve()
    else:
        product_root = Path(__file__).resolve().parents[2]
        try:
            result.update(runtime_install_info(product_root, product_root / "runtime-lock.json"))
        except ValueError as error:
            result["unavailable_reason"] = str(error)
    return result


def _prune_jobs(now: float | None = None) -> None:
    current = time.time() if now is None else now
    terminal = sorted((job for job in JOBS.values() if job["status"] in {"succeeded", "failed"}), key=lambda item: item["updated_at"], reverse=True)
    keep = {job["job_id"] for job in terminal[:100] if current - job["updated_at"] <= 24 * 60 * 60}
    for job_id in list(JOBS):
        if JOBS[job_id]["status"] in {"succeeded", "failed"} and job_id not in keep:
            JOBS.pop(job_id, None)


def _job_view(job: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in job.items() if key not in {"created_at", "updated_at"}}


def _strip_ansi(text: str) -> str:
    """Remove terminal control sequences from captured worker output."""
    return ANSI_ESCAPE.sub("", text)


def _backtest_process_error(output: str, returncode: int) -> str:
    lines = [line.strip() for line in _strip_ansi(output).splitlines() if line.strip()]
    for line in reversed(lines):
        if line.lower().startswith("error:"):
            return line.split(":", 1)[1].strip() or f"backtest worker exited with code {returncode}"
    for line in reversed(lines):
        lowered = line.lower()
        if "failed to initialize logging" in lowered or "panicked at" in lowered:
            return f"backtest worker exited with code {returncode}: {line[-1000:]}"
    detail = lines[-1][-1000:] if lines else "no diagnostic output"
    return f"backtest worker exited with code {returncode}: {detail}"


def _backtest_result(output: str, *, strategy: str, version: str, preset: str, days: int) -> dict[str, Any]:
    output = _strip_ansi(output)
    decoder = json.JSONDecoder()
    result: dict[str, Any] | None = None
    for index, character in enumerate(output):
        if character != "{":
            continue
        try:
            value, end = decoder.raw_decode(output, index)
        except json.JSONDecodeError:
            continue
        if not output[end:].strip() and isinstance(value, dict):
            result = value
            break
    if result is None:
        raise ValueError("backtest worker returned an invalid result")
    run_id = result.get("run_id")
    if (
        not isinstance(run_id, str)
        or not RUN_ID.fullmatch(run_id)
        or result.get("strategy") != strategy
        or result.get("version") != version
        or result.get("preset") != preset
        or result.get("days") != days
        or not (state_root() / "runs" / run_id / "run.json").is_file()
    ):
        raise ValueError("backtest worker result does not match the requested run")
    return result


def _run_backtest_process(strategy: str, version: str, preset: str, days: int) -> dict[str, Any]:
    """Run Nautilus in a disposable process so its global logger cannot kill the Dashboard."""
    product_root = Path(__file__).resolve().parents[2]
    source = product_root / "src"
    core = product_root / "core_src"
    if not core.is_dir():
        core = product_root.parent / "edgepilot-core" / "src"
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env["PYTHONPATH"] = os.pathsep.join([str(source), str(core)])
    completed = subprocess.run(
        [
            str(active_runtime_python()),
            "-m",
            "edgepilot_research.cli",
            "backtest",
            strategy,
            "--version",
            version,
            "--preset",
            preset,
            "--days",
            str(days),
        ],
        cwd=state_root(),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(_backtest_process_error(completed.stdout, completed.returncode))
    return _backtest_result(
        completed.stdout,
        strategy=strategy,
        version=version,
        preset=preset,
        days=days,
    )


def start_backtest(payload: dict[str, Any]) -> str:
    if set(payload) not in ({"strategy", "version", "preset", "days"}, {"strategy", "version", "preset", "days", "confirm_runtime"}):
        raise ValueError("backtest accepts only strategy, version, preset, days, and optional confirm_runtime")
    slug_value = payload.get("strategy")
    version_value = payload.get("version")
    preset_value = payload.get("preset")
    if not isinstance(slug_value, str) or not isinstance(version_value, str) or not isinstance(preset_value, str):
        raise ValueError("backtest fields must be strings")
    backtest_slug: str = slug_value
    backtest_version: str = version_value
    backtest_preset: str = preset_value
    installed = _installed(backtest_slug)
    if backtest_version != installed["version"] or backtest_preset not in installed["presets"]:
        raise ValueError("installed strategy version or preset does not match")
    days_value = payload.get("days")
    if type(days_value) is not int or days_value not in {90, 365}:
        raise ValueError("days must be 90 or 365")
    backtest_days: int = days_value
    runtime_missing = not runtime_status().get("installed")
    if runtime_missing and payload.get("confirm_runtime") is not True:
        raise ValueError("RUNTIME_CONFIRMATION_REQUIRED: confirm the locked Research runtime download")
    with JOBS_LOCK:
        _prune_jobs()
        if any(job["status"] in {"queued", "running"} for job in JOBS.values()):
            raise ConflictError("another backtest is already running")
        job_id = secrets.token_urlsafe(18)
        now = time.time()
        JOBS[job_id] = {"job_id": job_id, "status": "queued", "stage": "preparing", "message": "准备运行环境",
                        "downloaded_bytes": 0, "total_bytes": None, "percent": None,
                        "strategy": backtest_slug, "version": backtest_version, "preset": backtest_preset,
                        "days": backtest_days, "created_at": now, "updated_at": now}

    def worker() -> None:
        with JOBS_LOCK:
            job = JOBS[job_id]
            job.update(status="running", updated_at=time.time())
        try:
            if runtime_missing:
                product_root = Path(__file__).resolve().parents[2]
                def progress(stage: str, message: str, downloaded: int | None, total: int | None) -> None:
                    with JOBS_LOCK:
                        current = JOBS[job_id]
                        percent = round(downloaded * 100 / total, 1) if downloaded is not None and total else None
                        current.update(stage=stage, message=message, downloaded_bytes=downloaded or 0,
                                       total_bytes=total, percent=percent, updated_at=time.time())
                install_runtime(product_root, product_root / "runtime-lock.json", accept_download=True, progress_callback=progress)
            with JOBS_LOCK:
                JOBS[job_id].update(stage="starting_backtest", message="启动回测", percent=100, updated_at=time.time())
            result = _run_backtest_process(
                backtest_slug,
                backtest_version,
                backtest_preset,
                backtest_days,
            )
            update = {"status": "succeeded", "stage": "complete", "message": "回测完成", "run_id": result["run_id"]}
        except Exception as error:  # job must always reach a terminal state
            message = str(error)
            code = ("PUBLIC_DATA_UNSUPPORTED" if message.startswith("PUBLIC_DATA_UNSUPPORTED:")
                    else "PUBLIC_DATA_DOWNLOAD_FAILED" if message.startswith("PUBLIC_DATA_DOWNLOAD_FAILED:")
                    else "CATALOG_DATA_MISSING" if message.startswith("CATALOG_DATA_MISSING:")
                    else "BACKTEST_FAILED")
            update = {"status": "failed", "stage": "failed", "message": "运行环境安装或回测失败，可安全重试；推荐和历史结果不受影响。",
                      "error": {"code": code, "message": message}}
        with JOBS_LOCK:
            if job_id in JOBS:
                JOBS[job_id].update(update, updated_at=time.time())

    Thread(target=worker, daemon=True).start()
    return job_id


def remove_strategy(slug: str) -> None:
    installed = _installed(slug)
    target = _strategy_directory(slug)
    if installed["slug"] != slug or target.parent != state_root() / "strategies":
        raise ValueError("strategy install identity is inconsistent")
    shutil.rmtree(target)


def _json_response(handler: BaseHTTPRequestHandler, payload: Any, status: int = 200, headers: dict[str, str] | None = None) -> None:
    body = json.dumps(payload, ensure_ascii=False, default=str).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.send_header("Referrer-Policy", "no-referrer")
    for name, value in (headers or {}).items():
        handler.send_header(name, value)
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _error(handler: BaseHTTPRequestHandler, code: str, message: str, status: int, details: dict[str, Any] | None = None) -> None:
    _json_response(handler, {"error": {"code": code, "message": message, "details": details or {}}}, status)


def _remote_error(handler: BaseHTTPRequestHandler, error: urllib.error.HTTPError) -> None:
    if error.code == 429:
        raw = error.headers.get("Retry-After", "") if error.headers else ""
        retry_after = int(raw) if raw.isdigit() and 0 < int(raw) <= 3600 else None
        details = {"retry_after": retry_after} if retry_after is not None else {}
        _error(handler, "REMOTE_RATE_LIMITED", "Research Marketplace is rate limited", 503, details)
    else:
        _error(handler, "REMOTE_HTTP_ERROR", f"Research Marketplace returned HTTP {error.code}", 502, {"status": error.code})


def _recommendation_error(handler: BaseHTTPRequestHandler, error: ResearchRecommendationError) -> None:
    messages = {
        "INVALID_REQUEST": "The questionnaire is invalid",
        "INVALID_ARGUMENT": "The questionnaire contains an invalid answer",
        "REQUEST_TOO_LARGE": "The questionnaire is too large",
        "CATALOG_COVERAGE_INSUFFICIENT": "The Research catalog cannot provide three recommendations right now",
        "RATE_LIMITED": "Too many recommendation requests; try again later",
        "INTERNAL_ERROR": "The recommendation service is temporarily unavailable",
        "SERVICE_UNAVAILABLE": "The recommendation service is temporarily unavailable",
        "REMOTE_HTTP_ERROR": "The recommendation service returned an unsupported error",
    }
    payload: dict[str, Any] = {
        "code": error.code,
        "message": messages[error.code],
        "retryable": error.retryable,
    }
    if error.retry_after is not None:
        payload["retry_after"] = error.retry_after
    status = 503 if error.status in {500, 503} else error.status
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else None
    _json_response(handler, {"error": payload}, status, headers)


def _download_error_response(handler: BaseHTTPRequestHandler, error: ResearchDownloadError) -> None:
    if isinstance(error, ResearchDownloadQuotaError):
        payload: dict[str, Any] = {
            "code": error.code,
            "message": "当前来源网络下载额度已用尽",
            "retryable": True,
            "limiting_scopes": error.limiting_scopes,
            "quotas": error.quotas,
        }
        if error.request_id is not None:
            payload["request_id"] = error.request_id
        return _json_response(
            handler,
            {"error": payload},
            429,
            {"Retry-After": str(error.retry_after)},
        )
    payload: dict[str, Any] = {
        "code": error.code,
        "message": (
            "Research strategy download quota service is temporarily unavailable"
            if error.code == "DOWNLOAD_QUOTA_UNAVAILABLE"
            else "Too many strategy download requests; try again later"
            if error.code == "RATE_LIMITED"
            else "Research strategy download failed"
        ),
        "retryable": error.retryable,
    }
    if error.retry_after is not None:
        payload["retry_after"] = error.retry_after
    if error.request_id is not None:
        payload["request_id"] = error.request_id
    headers = {"Retry-After": str(error.retry_after)} if error.retry_after is not None else None
    _json_response(handler, {"error": payload}, error.status, headers)


def _network_error(handler: BaseHTTPRequestHandler, error: urllib.error.URLError) -> None:
    reason = error.reason
    if isinstance(reason, socket.gaierror):
        _error(handler, "DNS_FAILED", "Research Marketplace hostname could not be resolved", 503)
    elif isinstance(reason, (TimeoutError, socket.timeout)):
        _error(handler, "CONNECT_TIMEOUT", "Research Marketplace connection timed out", 504)
    else:
        _error(handler, "REMOTE_CONNECTION_FAILED", "Research Marketplace connection failed", 503)


def marketplace_preflight() -> None:
    """Require catalog connectivity before exposing an install-capable Dashboard."""
    try:
        search(limit=1)
    except urllib.error.HTTPError as error:
        raise ValueError(f"REMOTE_HTTP_ERROR: Research Marketplace returned HTTP {error.code}") from error
    except urllib.error.URLError as error:
        reason = error.reason
        if isinstance(reason, socket.gaierror):
            code = "DNS_FAILED"
        elif isinstance(reason, (TimeoutError, socket.timeout)):
            code = "CONNECT_TIMEOUT"
        else:
            code = "REMOTE_CONNECTION_FAILED"
        raise ValueError(f"{code}: start the Research Dashboard with outbound network permission") from error


class Handler(BaseHTTPRequestHandler):
    server_version = "EdgePilotResearch/1.0"

    def log_message(self, format: str, *args: Any) -> None:
        del format
        LOGGER.info("research dashboard request", extra={"method": self.command, "path": urlparse(str(self.path)).path, "status": args[1] if len(args) > 1 else None})

    def _origin(self) -> str:
        host, port = self.server.server_address[:2]
        display = f"[{host}]" if ":" in host else host
        return f"http://{display}:{port}"

    def _valid_host(self) -> bool:
        return self.headers.get("Host") == self._origin().removeprefix("http://")

    def _valid_write(self) -> bool:
        token = getattr(self.server, "research_csrf", "")
        return (
            self._valid_host()
            and isinstance(token, str)
            and self.headers.get("Origin") == self._origin()
            and secrets.compare_digest(str(self.headers.get("X-EdgePilot-CSRF", "")), token)
        )

    def _body(self) -> dict[str, Any]:
        if self.headers.get_content_type() != "application/json":
            raise ValueError("Content-Type must be application/json")
        length = int(self.headers.get("Content-Length", "0"))
        if length < 0 or length > MAX_BODY:
            raise OverflowError("request body exceeds 16 KiB")
        value = json.loads(self.rfile.read(length) or b"{}")
        if not isinstance(value, dict):
            raise ValueError("request body must be a JSON object")
        return value

    def _asset(self, relative: str) -> None:
        decoded = unquote(relative)
        if "\\" in decoded or "\0" in decoded:
            raise FileNotFoundError
        target = (ASSETS / decoded).resolve()
        root = ASSETS.resolve()
        if target != root and root not in target.parents:
            raise FileNotFoundError
        if not target.is_file():
            raise FileNotFoundError
        body = target.read_bytes()
        mime = mimetypes.guess_type(target.name)[0] or "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", f"{mime}; charset=utf-8" if mime.startswith("text/") else mime)
        self.send_header("Cache-Control", "public, max-age=31536000, immutable" if re.search(r"-[A-Za-z0-9_-]{8,}\.", target.name) else "no-store")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(str(self.path))
        parsed_path = str(parsed.path)
        try:
            if not self._valid_host():
                return _error(self, "INVALID_HOST", "invalid Host header", 400)
            if parsed_path == "/":
                return self._asset("index.html")
            if parsed_path.startswith("/assets/") or parsed_path.startswith("/brand/"):
                return self._asset(parsed_path.removeprefix("/"))
            if parsed_path == "/api/bootstrap":
                return _json_response(self, {"csrf_token": getattr(self.server, "research_csrf", "")})
            if parsed_path == "/api/config":
                return _json_response(self, {"product": "edgepilot-research", "version": __version__, "locales": list(LOCALES), "runtime": _safe_runtime(), "process": getattr(self.server, "research_identity", {})})
            if parsed_path == "/api/health":
                identity = getattr(self.server, "edgepilot_identity", None)
                if isinstance(identity, dict) and secrets.compare_digest(str(self.headers.get("X-EdgePilot-Instance", "")), str(identity.get("instance_nonce", ""))):
                    return _json_response(self, identity)
                return _json_response(self, {"ok": True, **getattr(self.server, "research_identity", {})})
            query: dict[str, list[str]] = parse_qs(str(parsed.query), keep_blank_values=True)
            if parsed_path == "/api/marketplace/strategies":
                return _json_response(self, search(
                    query.get("q", [""])[0],
                    sort=query.get("sort", ["published"])[0],
                    locale=_locale(query.get("locale", ["en"])[0]),
                    limit=int(query.get("limit", ["100"])[0]),
                    venue=query.get("venue", [""])[0],
                ))
            match = re.fullmatch(r"/api/marketplace/strategies/([^/]+)/versions", parsed_path)
            if match:
                return _json_response(self, versions(match.group(1)))
            match = re.fullmatch(r"/api/marketplace/strategies/([^/]+)/([^/]+)", parsed_path)
            if match:
                return _json_response(self, inspect(match.group(1), match.group(2), locale=_locale(query.get("locale", ["en"])[0])))
            if parsed_path == "/api/strategies":
                return _json_response(self, strategy_records(_locale(query.get("locale", ["en"])[0])))
            match = re.fullmatch(r"/api/strategies/([^/]+)", parsed_path)
            if match:
                return _json_response(self, _installed(match.group(1)))
            if parsed_path == "/api/runs":
                return _json_response(self, run_records(query.get("strategy", [""])[0]))
            if parsed_path == "/api/jobs":
                with JOBS_LOCK:
                    _prune_jobs()
                    return _json_response(self, [_job_view(job) for job in sorted(JOBS.values(), key=lambda row: row["updated_at"], reverse=True)])
            match = re.fullmatch(r"/api/runs/([^/]+)", parsed_path)
            if match:
                return _json_response(self, run_detail(match.group(1)))
            match = re.fullmatch(r"/api/jobs/([^/]+)", parsed_path)
            if match:
                if not JOB_ID.fullmatch(match.group(1)):
                    raise ValueError("invalid job id")
                with JOBS_LOCK:
                    _prune_jobs()
                    job = JOBS.get(match.group(1))
                    if job is None:
                        raise FileNotFoundError("job not found")
                    return _json_response(self, _job_view(job))
            return _error(self, "NOT_FOUND", "not found", 404)
        except urllib.error.HTTPError as error:
            return _remote_error(self, error)
        except urllib.error.URLError as error:
            return _network_error(self, error)
        except FileNotFoundError:
            return _error(self, "NOT_FOUND", "not found", 404)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(self, "VALIDATION_FAILED", str(error), 400)
        except Exception:
            LOGGER.exception("research dashboard GET failed")
            return _error(self, "INTERNAL_ERROR", "internal request failure", 500)

    def do_POST(self) -> None:  # noqa: N802
        try:
            if not self._valid_write():
                return _error(self, "CSRF_REJECTED", "invalid Host, Origin, or CSRF token", 403)
            payload = self._body()
            if self.path == "/api/behavior-events":
                from .behavior_events import record_behavior_event
                record_behavior_event(payload)
                return _json_response(self, {"accepted": True}, 202)
            if self.path == "/api/marketplace/recommendations":
                if set(payload) != RECOMMENDATION_FIELDS:
                    raise ValueError("recommendation accepts only the canonical V2 questionnaire fields")
                return _json_response(self, recommend(payload))
            if self.path == "/api/marketplace/install":
                if set(payload) != {"slug", "version"} or not all(isinstance(payload[key], str) for key in payload):
                    raise ValueError("install accepts only slug and version strings")
                install(payload["slug"], payload["version"])
                return _json_response(self, _installed(payload["slug"]), 201)
            if self.path == "/api/backtests":
                return _json_response(self, {"job_id": start_backtest(payload)}, 202)
            if self.path == "/api/process/stop":
                if set(payload) != {"instance_nonce"} or not isinstance(payload["instance_nonce"], str):
                    raise ValueError("stop accepts only instance_nonce")
                identity = getattr(self.server, "research_identity", {})
                if not secrets.compare_digest(payload["instance_nonce"], str(identity.get("instance_nonce", ""))):
                    return _error(self, "INSTANCE_MISMATCH", "Dashboard instance does not match", 409)
                with JOBS_LOCK:
                    if any(job["status"] in {"queued", "running"} for job in JOBS.values()):
                        raise ConflictError("a backtest is still running")
                _json_response(self, {"stopping": True, "instance_nonce": identity["instance_nonce"]}, 202)
                Thread(target=self.server.shutdown, daemon=True).start()
                return None
            return _error(self, "NOT_FOUND", "not found", 404)
        except ResearchRecommendationError as error:
            return _recommendation_error(self, error)
        except ResearchDownloadError as error:
            return _download_error_response(self, error)
        except ConflictError as error:
            return _error(self, "CONFLICT", str(error), 409)
        except InstallConflictError as error:
            return _error(self, "CONFLICT", str(error), 409)
        except DigestMismatchError as error:
            return _error(self, "DIGEST_MISMATCH", str(error), 422)
        except OverflowError as error:
            return _error(self, "VALIDATION_FAILED", str(error), 413)
        except FileNotFoundError:
            return _error(self, "NOT_FOUND", "not found", 404)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            message = str(error)
            runtime_code = next((code for code in ("RUNTIME_NOT_INSTALLED", "RUNTIME_INCOMPLETE", "RUNTIME_PROCESS_STALE", "RUNTIME_VERSION_MISMATCH") if message.startswith(f"{code}:")), None)
            return _error(self, runtime_code or "VALIDATION_FAILED", message, 409 if runtime_code == "RUNTIME_PROCESS_STALE" else 400)
        except urllib.error.HTTPError as error:
            return _remote_error(self, error)
        except urllib.error.URLError as error:
            return _network_error(self, error)
        except OSError:
            LOGGER.exception("research dashboard local install failed")
            return _error(self, "LOCAL_IO_ERROR", "local strategy installation failed", 500)

    def do_DELETE(self) -> None:  # noqa: N802
        try:
            if not self._valid_write() or self.headers.get("X-EdgePilot-Confirm") != "delete":
                return _error(self, "CSRF_REJECTED", "invalid confirmation, Host, Origin, or CSRF token", 403)
            match = re.fullmatch(r"/api/strategies/([^/]+)", str(urlparse(str(self.path)).path))
            if not match:
                return _error(self, "NOT_FOUND", "not found", 404)
            remove_strategy(match.group(1))
            return _json_response(self, {"deleted": True, "slug": match.group(1)})
        except FileNotFoundError:
            return _error(self, "NOT_FOUND", "not found", 404)
        except ValueError as error:
            return _error(self, "VALIDATION_FAILED", str(error), 400)


def create_server(host: str, port: int, *, instance_nonce: str | None = None) -> ThreadingHTTPServer:
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise ValueError("Research UI must bind to loopback")
    handler = cast(Callable[[Any, Any, ThreadingHTTPServer], BaseHTTPRequestHandler], Handler)
    server = ThreadingHTTPServer((host, port), handler)
    server.research_csrf = secrets.token_urlsafe(32)  # type: ignore[attr-defined]
    bound_host, bound_port = server.server_address[:2]
    server.research_identity = _dashboard_identity(str(bound_host), int(bound_port), instance_nonce or secrets.token_urlsafe(24))  # type: ignore[attr-defined]
    return server


def serve(host: str, port: int) -> None:
    if not (ASSETS / "index.html").is_file():
        raise ValueError("Research Dashboard assets are missing; rebuild edgepilot-research/ui")
    marketplace_preflight()
    root = state_root()
    nonce = secrets.token_urlsafe(24)
    _acquire_dashboard_lock(root, nonce)
    server: ThreadingHTTPServer | None = None
    try:
        server = create_server(host, port, instance_nonce=nonce)
        identity = getattr(server, "research_identity")
        _atomic_json(root / DASHBOARD_RECORD, identity)
        display = f"[{host}]" if ":" in host else host
        print(f"EdgePilot Research UI: http://{display}:{server.server_address[1]}")
        server.serve_forever()
    finally:
        if server is not None:
            server.server_close()
        _release_dashboard_lock(root, nonce)
