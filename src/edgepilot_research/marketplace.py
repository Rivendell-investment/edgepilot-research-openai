from __future__ import annotations

import hashlib
import io
import json
import os
import re
import secrets
import shutil
import tempfile
import time
import urllib.parse
import urllib.error
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any

from . import __version__
from .paths import state_root
ORIGIN = os.environ.get("EDGEPILOT_RESEARCH_ORIGIN", "https://edge-pilot.rivendell.capital").rstrip("/")
IDENTIFIER = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]{0,63}$")
RECOMMENDATION_FIELDS = {
    "questionnaire_version", "profit_style", "holding_period", "pain_point",
    "max_drawdown_pct", "trading_mode", "allocation_band", "universe", "locale",
}
RECOMMENDATION_ERRORS: dict[int, set[str]] = {
    400: {"INVALID_REQUEST", "INVALID_ARGUMENT"},
    413: {"REQUEST_TOO_LARGE"},
    409: {"CATALOG_COVERAGE_INSUFFICIENT"},
    429: {"RATE_LIMITED"},
    500: {"INTERNAL_ERROR"},
    503: {"SERVICE_UNAVAILABLE", "INTERNAL_ERROR"},
}


class InstallConflictError(ValueError):
    """An install cannot proceed without choosing between local candidates."""


class DigestMismatchError(ValueError):
    """Published package integrity metadata or bytes do not agree."""


class ResearchRecommendationError(Exception):
    """A safe, structured failure returned by the Research recommendation API."""

    def __init__(self, code: str, status: int, retryable: bool, retry_after: int | None = None) -> None:
        super().__init__(code)
        self.code = code
        self.status = status
        self.retryable = retryable
        self.retry_after = retry_after


def _json(path: str, query: dict[str, str] | None = None) -> dict[str, Any]:
    url = f"{ORIGIN}{path}"
    if query:
        url += "?" + urllib.parse.urlencode({key: value for key, value in query.items() if value})
    request = urllib.request.Request(url, headers=_headers())
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = response.read(2 * 1024 * 1024 + 1)
    if len(payload) > 2 * 1024 * 1024:
        raise ValueError("Research service returned an oversized response")
    value = json.loads(payload)
    if not isinstance(value, dict):
        raise ValueError("Research service returned an invalid response")
    return value


def search(query: str = "", *, sort: str = "published", locale: str = "en", limit: int = 100) -> dict[str, Any]:
    if not isinstance(query, str) or len(query) > 200:
        raise ValueError("Marketplace query must be at most 200 characters")
    if sort not in {"published", "return", "drawdown", "sharpe"}:
        raise ValueError("Invalid Marketplace sort")
    if type(limit) is not int or limit < 1 or limit > 100:
        raise ValueError("Marketplace limit must be from 1 to 100")
    return _json("/api/research/strategies", {"q": query, "sort": sort, "locale": locale, "limit": str(limit)})


def recommend(questionnaire: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(questionnaire, dict) or set(questionnaire) != RECOMMENDATION_FIELDS:
        raise ValueError("recommendation accepts only the canonical V2 questionnaire fields")
    payload = json.dumps(questionnaire, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if len(payload) > 16 * 1024:
        raise ValueError("recommendation questionnaire exceeds 16 KiB")
    headers = {**_headers(), "content-type": "application/json"}
    request = urllib.request.Request(
        f"{ORIGIN}/api/research/recommendations", data=payload, headers=headers, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read(2 * 1024 * 1024 + 1)
    except urllib.error.HTTPError as error:
        try:
            raw = error.read(2 * 1024 * 1024 + 1)
        finally:
            error.close()
        try:
            value = json.loads(raw) if len(raw) <= 2 * 1024 * 1024 else None
        except (UnicodeDecodeError, json.JSONDecodeError):
            value = None
        detail = value.get("error") if isinstance(value, dict) else None
        code = detail.get("code") if isinstance(detail, dict) else None
        retryable = detail.get("retryable") if isinstance(detail, dict) else None
        if code not in RECOMMENDATION_ERRORS.get(error.code, set()) or type(retryable) is not bool:
            raise ResearchRecommendationError("REMOTE_HTTP_ERROR", 502, True) from error
        retry_after = _retry_after(error.headers.get("Retry-After", "") if error.headers else "") if error.code == 429 else None
        raise ResearchRecommendationError(code, error.code, retryable, retry_after) from error
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError("Research service returned an oversized response")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise ValueError("Research service returned an invalid response")
    return value


def _retry_after(raw: str) -> int | None:
    return int(raw) if raw.isdigit() and 0 < int(raw) <= 3600 else None


def inspect(slug: str, version: str, *, locale: str = "en") -> dict[str, Any]:
    _validate(slug, version)
    return _json(f"/api/research/strategies/{slug}/{version}", {"locale": locale})


def versions(slug: str) -> dict[str, Any]:
    _validate(slug)
    return _json(f"/api/research/strategies/{slug}/versions")


def install(slug: str, version: str) -> Path:
    _validate(slug, version)
    detail = inspect(slug, version).get("strategy", {})
    expected = str(detail.get("package_sha256", ""))
    expected_bytes = detail.get("package_bytes")
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise DigestMismatchError("Research package is missing its SHA-256 digest")
    if type(expected_bytes) is not int or expected_bytes < 1 or expected_bytes > 20 * 1024 * 1024:
        raise ValueError("Research package size is invalid")
    url = f"{ORIGIN}/api/research/strategies/{slug}/{version}/download"
    with urllib.request.urlopen(urllib.request.Request(url, headers=_headers()), timeout=60) as response:
        length = response.headers.get("Content-Length")
        digest_header = response.headers.get("X-Package-SHA256")
        if length is not None and (not length.isdigit() or int(length) != expected_bytes):
            raise DigestMismatchError("Research package Content-Length differs from its published metadata")
        if digest_header is not None and digest_header != expected:
            raise DigestMismatchError("Research package digest header differs from its published metadata")
        archive = response.read(20 * 1024 * 1024 + 1)
    if len(archive) != expected_bytes or hashlib.sha256(archive).hexdigest() != expected:
        raise DigestMismatchError("Research package digest or size is invalid")
    target = state_root() / "strategies" / slug.replace("-", "_")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="edgepilot-research-install-", dir=target.parent) as temporary:
        staging = Path(temporary) / "package"; staging.mkdir()
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            total = 0
            names: set[str] = set()
            if len(package.infolist()) > 200:
                raise ValueError("Research package contains too many files")
            for item in package.infolist():
                path = PurePosixPath(item.filename)
                if path.is_absolute() or ".." in path.parts or item.is_dir() or (item.external_attr >> 16) & 0o170000 == 0o120000:
                    if item.is_dir():
                        continue
                    raise ValueError("Research package contains an unsafe path")
                normalized = path.as_posix()
                if normalized in names:
                    raise ValueError("Research package contains duplicate paths")
                names.add(normalized)
                total += item.file_size
                if item.file_size > 10 * 1024 * 1024 or total > 40 * 1024 * 1024:
                    raise ValueError("Research package expands beyond its limit")
                destination = staging.joinpath(*path.parts); destination.parent.mkdir(parents=True, exist_ok=True)
                with package.open(item) as source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
        required = ("marketplace.json", "__init__.py", "strategy.py")
        missing = [name for name in required if not (staging / name).is_file()]
        if missing:
            raise ValueError(f"Research package is missing required files: {', '.join(missing)}")
        manifest = json.loads((staging / "marketplace.json").read_text(encoding="utf-8"))
        if manifest.get("slug") != slug or manifest.get("version") != version:
            raise ValueError("Research package identity differs from the requested strategy")
        benchmark = manifest.get("benchmark")
        preset = benchmark.get("preset") if isinstance(benchmark, dict) else None
        preset = preset if isinstance(preset, str) and preset else "default"
        if not (staging / "configs" / f"{preset}.json").is_file():
            raise ValueError(f"Research package is missing benchmark preset {preset!r}")
        (staging / ".edgepilot-install.json").write_text(json.dumps({"schema_version": 1, "slug": slug, "version": version, "package_sha256": expected}, sort_keys=True) + "\n", encoding="utf-8")
        install_lock = target.with_name(target.name + ".install-lock")
        _acquire_install_lock(target, install_lock)
        (install_lock / "owner.json").write_text(
            json.dumps({"pid": os.getpid(), "created_at": int(time.time())}) + "\n",
            encoding="utf-8",
        )
        backup = target.with_name(target.name + f".previous-{os.getpid()}-{secrets.token_hex(4)}")
        try:
            if target.exists():
                target.rename(backup)
            try:
                staging.rename(target)
            except Exception:
                if not target.exists() and backup.exists():
                    backup.rename(target)
                raise
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if backup.exists() and target.exists():
                shutil.rmtree(backup)
            shutil.rmtree(install_lock, ignore_errors=True)
    return target


def _validate(slug: str, version: str | None = None) -> None:
    if not IDENTIFIER.fullmatch(slug) or (version is not None and not VERSION.fullmatch(version)):
        raise ValueError("Invalid strategy identifier")


def _headers() -> dict[str, str]:
    return {"accept": "application/json", "user-agent": f"edgepilot-research/{__version__}"}


def _acquire_install_lock(target: Path, install_lock: Path) -> None:
    """Acquire the per-strategy lock, recovering only an unambiguous old install."""
    try:
        install_lock.mkdir()
        return
    except FileExistsError:
        pass
    owner = install_lock / "owner.json"
    try:
        value = json.loads(owner.read_text(encoding="utf-8"))
        pid = value.get("pid") if isinstance(value, dict) else None
    except (OSError, ValueError, json.JSONDecodeError):
        pid = None
    if type(pid) is int and pid > 0 and _pid_is_alive(pid):
        raise InstallConflictError(f"another install is already changing {target.name.replace('_', '-')}")
    backups = sorted(target.parent.glob(target.name + ".previous-*"))
    if len(backups) > 1 or (target.exists() and backups):
        raise InstallConflictError("an interrupted install left multiple strategy candidates; manual recovery is required")
    if not target.exists() and len(backups) == 1:
        backups[0].rename(target)
    shutil.rmtree(install_lock)
    try:
        install_lock.mkdir()
    except FileExistsError as error:
        raise InstallConflictError(f"another install is already changing {target.name.replace('_', '-')}") from error


def _pid_is_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except (PermissionError, OSError):
        return True
    return True
