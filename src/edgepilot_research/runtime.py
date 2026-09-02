from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Callable

from .paths import state_root
from .process import pid_exists as _pid_exists

SCHEMA = "edgepilot-research-runtime-v1"
SHA256 = re.compile(r"^[0-9a-f]{64}$")
DIST = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.!+_-]*$")
LOCK_FIELDS = {"schema_version", "nautilus_version", "runtimes"}
RUNTIME_FIELDS = {"id", "os", "arch", "python_version", "python_tag", "total_bytes", "wheelhouse_sha256", "wheels"}
WHEEL_FIELDS = {"distribution", "version", "filename", "url", "bytes", "sha256"}
WHEEL_OPTIONAL_FIELDS = {"etag"}
NAUTILUS_ORIGIN = ("https", "pub-159c6bd6a09646de8b4b871989755240.r2.dev", None)
PYPI_ORIGIN = ("https", "files.pythonhosted.org", None)
DOWNLOAD_USER_AGENT = (
    "Mozilla/5.0 (compatible; EdgePilot-Research-Installer/1; +https://edge-pilot.rivendell.capital)"
)
INTEL_MAC_UNSUPPORTED = (
    "This Mac uses an Intel processor, which EdgePilot Research does not support. "
    "Supported Mac computers use Apple Silicon (M-series, arm64). "
    "No runtime files were downloaded or changed."
)
ROSETTA_UNSUPPORTED = (
    "This is an Apple Silicon Mac, but the installer is running through Rosetta as x86_64. "
    "Use a native arm64 Terminal and Python, then try again. "
    "No runtime files were downloaded or changed."
)


@dataclass(frozen=True)
class Wheel:
    distribution: str
    version: str
    filename: str
    url: str
    bytes: int
    sha256: str
    etag: str | None = None


@dataclass(frozen=True)
class RuntimeEntry:
    id: str
    os: str
    arch: str
    python_version: str
    python_tag: str
    total_bytes: int
    wheelhouse_sha256: str
    wheels: tuple[Wheel, ...]


@dataclass(frozen=True)
class RuntimeLock:
    sha256: str
    canonical: bytes
    nautilus_version: str
    runtimes: tuple[RuntimeEntry, ...]


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"runtime lock contains duplicate key: {key}")
        value[key] = item
    return value


def load_lock(path: Path) -> RuntimeLock:
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"cannot read runtime lock: {error}") from error
    if not isinstance(value, dict) or set(value) != LOCK_FIELDS or value.get("schema_version") != SCHEMA:
        raise ValueError("runtime lock has invalid schema or fields")
    if not VERSION.fullmatch(str(value.get("nautilus_version", ""))):
        raise ValueError("runtime lock has invalid Nautilus version")
    rows = value.get("runtimes")
    if not isinstance(rows, list) or not rows:
        raise ValueError("runtime lock must contain runtimes")
    runtimes = tuple(_parse_runtime(row) for row in rows)
    identities = [(row.os, row.arch) for row in runtimes]
    if len({row.id for row in runtimes}) != len(runtimes) or len(set(identities)) != len(runtimes):
        raise ValueError("runtime ids and OS/architecture pairs must be unique")
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
    return RuntimeLock(hashlib.sha256(canonical).hexdigest(), canonical, str(value["nautilus_version"]), runtimes)


def _parse_runtime(value: Any) -> RuntimeEntry:
    if not isinstance(value, dict) or set(value) != RUNTIME_FIELDS:
        raise ValueError("runtime entry has unknown or missing fields")
    os_name, arch = str(value["os"]), str(value["arch"])
    if os_name not in {"macos", "windows", "linux"} or arch not in {"arm64", "amd64", "x86_64"}:
        raise ValueError("runtime OS or architecture is invalid")
    python_version, python_tag = str(value["python_version"]), str(value["python_tag"])
    match = re.fullmatch(r"3\.(\d+)", python_version)
    if not match or python_tag != f"cp3{match.group(1)}":
        raise ValueError("runtime Python version and tag disagree")
    wheels_value = value["wheels"]
    if not isinstance(wheels_value, list) or not wheels_value:
        raise ValueError("runtime wheelhouse is empty")
    wheels = tuple(_parse_wheel(row) for row in wheels_value)
    names = [wheel.distribution for wheel in wheels]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ValueError("runtime wheels must have unique sorted distributions")
    total = sum(wheel.bytes for wheel in wheels)
    if type(value["total_bytes"]) is not int or value["total_bytes"] != total:
        raise ValueError("runtime total_bytes does not match wheels")
    digest_input = "".join(
        f"{wheel.distribution}=={wheel.version}\0{wheel.filename}\0{wheel.bytes}\0{wheel.sha256}\n" for wheel in wheels
    ).encode()
    wheelhouse_sha = str(value["wheelhouse_sha256"])
    if not SHA256.fullmatch(wheelhouse_sha) or hashlib.sha256(digest_input).hexdigest() != wheelhouse_sha:
        raise ValueError("runtime wheelhouse digest is invalid")
    expected_id = f"{os_name}-{arch}-{python_tag}"
    if value["id"] != expected_id:
        raise ValueError(f"runtime id must be {expected_id}")
    return RuntimeEntry(expected_id, os_name, arch, python_version, python_tag, total, wheelhouse_sha, wheels)


def _parse_wheel(value: Any) -> Wheel:
    if not isinstance(value, dict) or not WHEEL_FIELDS.issubset(value) or set(value) - WHEEL_FIELDS - WHEEL_OPTIONAL_FIELDS:
        raise ValueError("wheel entry has unknown or missing fields")
    raw_distribution = str(value["distribution"])
    distribution = re.sub(r"[-_.]+", "-", raw_distribution).lower()
    filename, version, url = str(value["filename"]), str(value["version"]), str(value["url"])
    parsed = urllib.parse.urlsplit(url)
    if raw_distribution != distribution or not DIST.fullmatch(distribution) or not VERSION.fullmatch(version):
        raise ValueError("wheel distribution or version is invalid")
    if PurePosixPath(filename).name != filename or not filename.endswith(".whl") or urllib.parse.unquote(PurePosixPath(parsed.path).name) != filename:
        raise ValueError("wheel filename or URL path is invalid")
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("wheel URL must be credential-free HTTPS without query or fragment")
    size, digest, etag = value["bytes"], str(value["sha256"]), value.get("etag")
    if type(size) is not int or size <= 0 or not SHA256.fullmatch(digest) or (etag is not None and (not isinstance(etag, str) or not etag or any(ch in etag for ch in "\r\n"))):
        raise ValueError("wheel size, digest, or ETag is invalid")
    return Wheel(distribution, version, filename, url, size, digest, etag)


def macos_process_is_translated() -> bool:
    try:
        result = subprocess.run(
            ["/usr/sbin/sysctl", "-in", "sysctl.proc_translated"],
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError:
        return False
    return result.returncode == 0 and result.stdout.strip() == "1"


def current_platform() -> tuple[str, str]:
    os_name = {"darwin": "macos", "windows": "windows", "linux": "linux"}.get(platform.system().lower())
    machine = platform.machine().lower()
    if os_name == "macos" and machine in {"x86_64", "amd64"}:
        if macos_process_is_translated():
            raise ValueError(ROSETTA_UNSUPPORTED)
        raise ValueError(INTEL_MAC_UNSUPPORTED)
    arch = {"aarch64": "arm64", "arm64": "arm64", "amd64": "amd64", "x86_64": "x86_64"}.get(machine)
    if os_name == "windows" and arch == "x86_64":
        arch = "amd64"
    if not os_name or not arch:
        raise ValueError(f"unsupported platform: {platform.system()} {platform.machine()}")
    return os_name, arch


def select_runtime(lock: RuntimeLock, identity: tuple[str, str] | None = None) -> RuntimeEntry:
    os_name, arch = identity or current_platform()
    matches = [entry for entry in lock.runtimes if (entry.os, entry.arch) == (os_name, arch)]
    if len(matches) != 1:
        raise ValueError(f"unsupported runtime: {os_name}-{arch}")
    return matches[0]


def runtime_status(home: Path | None = None) -> dict[str, Any]:
    root = (home or state_root()).resolve()
    path = root / "runtime.json"
    if not path.is_file():
        return {"installed": False, "home": str(root)}
    value = _read_state(path, root)
    release = root / value["active_release"]
    return {**value, "installed": release.is_dir(), "home": str(root), "release_exists": release.is_dir()}


def require_active_runtime(home: Path | None = None) -> dict[str, Any]:
    """Require this process to be running from the currently active release."""
    root = (home or state_root()).resolve()
    try:
        status = runtime_status(root)
    except ValueError as error:
        raise ValueError(f"RUNTIME_INCOMPLETE: {error}") from error
    if not status.get("installed"):
        raise ValueError("RUNTIME_NOT_INSTALLED: install the Research runtime before continuing")
    release = (root / str(status["active_release"])).resolve()
    expected_release_id = hashlib.sha256(
        (str(status["plugin_content_digest"]) + str(status["runtime_lock_sha256"]) + str(status["wheelhouse_sha256"])).encode()
    ).hexdigest()
    if release.name != expected_release_id:
        raise ValueError("RUNTIME_VERSION_MISMATCH: active release identity differs from runtime state")
    try:
        installed_lock = load_lock(release / "app" / "runtime-lock.json")
    except ValueError as error:
        raise ValueError(f"RUNTIME_INCOMPLETE: {error}") from error
    entry = next((row for row in installed_lock.runtimes if row.id == status["runtime_id"]), None)
    if installed_lock.sha256 != status["runtime_lock_sha256"] or entry is None or entry.wheelhouse_sha256 != status["wheelhouse_sha256"]:
        raise ValueError("RUNTIME_VERSION_MISMATCH: installed lock differs from runtime state")
    expected_python = _venv_python(release / ".venv").resolve()
    if not expected_python.is_file():
        raise ValueError("RUNTIME_INCOMPLETE: active runtime Python is unavailable")
    expected_prefix = (release / ".venv").resolve()
    if Path(sys.prefix).resolve() != expected_prefix:
        raise ValueError("RUNTIME_PROCESS_STALE: restart through the active Research runtime launcher")
    package = Path(__file__).resolve()
    app = (release / "app").resolve()
    # Also accept code loaded from the plugin's src layout (plugin/src/edgepilot_research/...)
    # so that subprocesses launched with PYTHONPATH pointing to the live plugin source work.
    in_src_layout = package.parent.parent.name == "src"
    if app not in package.parents and not in_src_layout:
        raise ValueError("RUNTIME_PROCESS_STALE: the process loaded Research code outside the active release")
    return {**status, "python_executable": str(Path(sys.executable).absolute()), "process_current": True}


def active_runtime_python(home: Path | None = None) -> Path:
    """Return the verified active runtime interpreter without requiring this process to run inside it."""
    root = (home or state_root()).resolve()
    status = runtime_status(root)
    if not status.get("installed"):
        raise ValueError("RUNTIME_NOT_INSTALLED: install the Research runtime before continuing")
    release = (root / str(status["active_release"])).resolve()
    if release.parent != (root / "releases").resolve():
        raise ValueError("RUNTIME_INCOMPLETE: active runtime release is unavailable")
    # A POSIX venv Python is normally a symlink to the base interpreter. Keep the
    # venv entry path so Python activates that venv when the Dashboard starts it.
    python = _venv_python(release / ".venv")
    if not python.is_file():
        raise ValueError("RUNTIME_INCOMPLETE: active runtime Python is unavailable")
    lock = load_lock(release / "app" / "runtime-lock.json")
    entry = next((row for row in lock.runtimes if row.id == status.get("runtime_id")), None)
    if lock.sha256 != status.get("runtime_lock_sha256") or entry is None or entry.wheelhouse_sha256 != status.get("wheelhouse_sha256"):
        raise ValueError("RUNTIME_VERSION_MISMATCH: installed lock differs from runtime state")
    return python


def runtime_install_info(plugin_root: Path, lock_path: Path, home: Path | None = None) -> dict[str, Any]:
    """Describe the locked download before the Dashboard asks for confirmation."""
    entry = select_runtime(load_lock(lock_path.resolve()))
    root = (home or state_root()).resolve()
    return {"product_name": "EdgePilot Research", "download_size": entry.total_bytes,
            "runtime_id": entry.id, "version": entry.python_version, "install_path": str(root / "releases")}


def format_bytes(value: int) -> str:
    return f"{value / (1024 * 1024):.1f} MiB"


def _progress(stage: str, message: str) -> None:
    print(f"[{stage}] {message}", file=sys.stderr, flush=True)


def _read_state(path: Path, home: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=_unique_object)
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError(f"runtime state is invalid: {error}") from error
    required = {"schema_version", "active_release", "previous_release", "plugin_version", "plugin_content_digest", "runtime_id", "runtime_lock_sha256", "wheelhouse_sha256", "installed_at"}
    if not isinstance(value, dict) or set(value) != required or value["schema_version"] != 1:
        raise ValueError("runtime state has unknown or missing fields")
    relative = PurePosixPath(str(value["active_release"]))
    if relative.is_absolute() or ".." in relative.parts or not relative.parts or relative.parts[0] != "releases":
        raise ValueError("runtime state contains an unsafe release path")
    previous = value["previous_release"]
    if previous is not None:
        previous_path = PurePosixPath(str(previous))
        if previous_path.is_absolute() or ".." in previous_path.parts or not previous_path.parts or previous_path.parts[0] != "releases":
            raise ValueError("runtime state contains an unsafe previous release path")
    if not SHA256.fullmatch(str(value["runtime_lock_sha256"])) or not SHA256.fullmatch(str(value["wheelhouse_sha256"])):
        raise ValueError("runtime state contains an invalid digest")
    return value


# Longest observed suffix under a release is about 110 characters
# (.venv\Lib\site-packages\nautilus_trader\core\*.pyd plus its DLL neighbors);
# beyond this prefix length Windows fails the final import with
# "DLL load failed: the filename or extension is too long".
_MAX_WINDOWS_RELEASE_PATH = 140


def _check_release_path_length(final: Path) -> None:
    if os.name != "nt" or len(str(final)) <= _MAX_WINDOWS_RELEASE_PATH:
        return
    raise ValueError(
        f"RUNTIME_PATH_TOO_LONG: release path {final} leaves too little room for the "
        "venv site-packages DLL paths that Windows must load. Unset a long "
        "EDGEPILOT_RESEARCH_HOME override to use %USERPROFILE%\\.edgepilot-research, "
        "or configure another short directory, then reinstall."
    )


def install_runtime(
    plugin_root: Path,
    lock_path: Path,
    *,
    accept_download: bool = False,
    home: Path | None = None,
    wheelhouse: Path | None = None,
    input_fn: Callable[[str], str] = input,
    progress_callback: Callable[[str, str, int | None, int | None], None] | None = None,
) -> dict[str, Any]:
    plugin_root = plugin_root.resolve()
    root = (home or state_root()).resolve()
    def emit(stage: str, message: str, downloaded: int | None = None, total: int | None = None) -> None:
        _progress(stage, message)
        if progress_callback is not None:
            progress_callback(stage, message, downloaded, total)

    emit("preparing", "Checking the runtime lock, platform, and CPython")
    lock = load_lock(lock_path.resolve())
    try:
        entry = select_runtime(lock)
    except ValueError as error:
        raise ValueError(f"RUNTIME_UNSUPPORTED: {error}") from error
    _validate_origins(entry)
    python = _matching_python(entry.python_version)
    root.mkdir(parents=True, exist_ok=True)
    required_disk = entry.total_bytes * 2 + 1024 * 1024 * 1024
    if shutil.disk_usage(root).free < required_disk:
        raise ValueError(f"runtime installation requires at least {required_disk} free bytes")
    if wheelhouse is not None:
        wheelhouse = wheelhouse.resolve()
        if not wheelhouse.is_dir():
            raise ValueError(f"wheelhouse is not a directory: {wheelhouse}")
    content_digest = _plugin_digest(plugin_root)
    release_id = hashlib.sha256((content_digest + lock.sha256 + entry.wheelhouse_sha256).encode()).hexdigest()
    releases = root / "releases"
    releases.mkdir(exist_ok=True)
    final = releases / release_id
    _check_release_path_length(final)
    lock_dir = _acquire_install_lock(root, release_id)
    staging = releases / f".staging-{release_id[:12]}-{os.getpid()}"
    try:
        existing_release = final.exists()
        if existing_release:
            _verify_release(final, entry)
        plan = [(wheel, "installed") for wheel in entry.wheels] if existing_release else _install_plan(root, entry, wheelhouse)
        downloaded = 0
        download_total = 0
        notice = _format_install_plan(root, entry, plan)
        print(notice, file=sys.stderr)
        if not existing_release and not accept_download and input_fn("Type 'yes' to continue: ").strip().lower() != "yes":
            raise ValueError("runtime download was not accepted")
        if existing_release:
            emit("verifying", "Verified the existing immutable runtime release")
        else:
            emit("preparing", "Preparing the isolated runtime release")
            staging.mkdir()
            _copy_app(plugin_root, staging / "app")
            cache = root / "cache" / "wheels" / entry.id
            cache.mkdir(parents=True, exist_ok=True)
            download_total = sum(wheel.bytes for wheel, source_kind in plan if source_kind == "download")
            emit("preparing", "Calculated the remaining runtime download", 0, download_total)
            total = len(plan)
            for index, (wheel, source_kind) in enumerate(plan, 1):
                action = {
                    "download": "Downloading",
                    "cache": "Reading and verifying local cache",
                    "local": "Reading and verifying local wheelhouse",
                }[source_kind]
                stage = "downloading" if source_kind == "download" else "verifying"
                emit(stage, f"{action} {index}/{total}: {wheel.filename} ({format_bytes(wheel.bytes)})", downloaded, download_total)
                source = wheelhouse / wheel.filename if source_kind == "local" and wheelhouse else None
                _obtain_wheel(
                    wheel,
                    cache / wheel.filename,
                    source,
                    progress=lambda current, _size, base=downloaded, network=source_kind == "download": emit(
                        "downloading" if network else "verifying",
                        (f"Downloaded {format_bytes(base + current)} / {format_bytes(download_total)}" if network
                         else f"Verified {wheel.filename}"),
                        base + current if network else base, download_total,
                    ),
                )
                if source_kind == "download":
                    downloaded += wheel.bytes
            emit("installing", f"Creating isolated CPython {entry.python_version} environment", downloaded, download_total)
            subprocess.run([str(python), "-m", "venv", str(staging / ".venv")], check=True, stdout=sys.stderr, stderr=sys.stderr)
            runtime_python = _venv_python(staging / ".venv")
            requirements = [f"{wheel.distribution}=={wheel.version}" for wheel in entry.wheels]
            environment = {**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}
            emit("installing", f"Installing {len(requirements)} locked wheels without dependency resolution", downloaded, download_total)
            subprocess.run([str(runtime_python), "-m", "pip", "--isolated", "install", "--no-index", "--no-deps", "--find-links", str(cache), *requirements], check=True, env=environment, stdout=sys.stderr, stderr=sys.stderr)
            emit("verifying", "Checking locked versions and importing the Research core", downloaded, download_total)
            subprocess.run([str(runtime_python), "-m", "pip", "check"], check=True, env=environment, stdout=sys.stderr, stderr=sys.stderr)
            _write_pth(runtime_python, staging / "app")
            _verify_release(staging, entry)
            staging.rename(final)
            try:
                _verify_release(final, entry)
            except Exception:
                final.rename(staging)
                raise
        previous = None
        state_path = root / "runtime.json"
        if state_path.exists():
            previous = _read_state(state_path, root)["active_release"]
        state = {
            "schema_version": 1,
            "active_release": f"releases/{release_id}",
            "previous_release": previous if previous != f"releases/{release_id}" else None,
            "plugin_version": _plugin_version(plugin_root),
            "plugin_content_digest": content_digest,
            "runtime_id": entry.id,
            "runtime_lock_sha256": lock.sha256,
            "wheelhouse_sha256": entry.wheelhouse_sha256,
            "installed_at": int(time.time()),
        }
        _atomic_json(root / "runtime.json", state)
        _write_launcher(root)
        emit("ready", f"Activated {entry.id}; launcher: {root / 'bin' / ('edgepilot-research.cmd' if os.name == 'nt' else 'edgepilot-research')}", downloaded, download_total)
        return state
    finally:
        if staging.exists():
            shutil.rmtree(staging)
        shutil.rmtree(lock_dir, ignore_errors=True)


def repair_runtime(*, home: Path | None = None, break_install_lock: bool = False) -> dict[str, Any]:
    root = (home or state_root()).resolve()
    lock_dir = root / "install.lock"
    if break_install_lock:
        if not lock_dir.is_dir():
            raise ValueError("no install lock exists")
        owner = json.loads((lock_dir / "owner.json").read_text(encoding="utf-8"))
        pid = int(owner["pid"])
        if _pid_exists(pid):
            raise ValueError(f"install process {pid} is still running")
        shutil.rmtree(lock_dir)
    root.mkdir(parents=True, exist_ok=True)
    operation_lock = _acquire_install_lock(root, "repair")
    try:
        status = runtime_status(root)
        if not status.get("installed"):
            raise ValueError("runtime is not installed; rerun the plugin's install_runtime.py")
        release = root / str(status["active_release"])
        runtime_python = _venv_python(release / ".venv")
        if not runtime_python.is_file():
            raise ValueError("active runtime is incomplete; rerun the plugin's install_runtime.py")
        lock = load_lock(release / "app" / "runtime-lock.json")
        if lock.sha256 != status["runtime_lock_sha256"]:
            raise ValueError("installed runtime lock differs from runtime state; rerun the plugin's install_runtime.py")
        entry = next((row for row in lock.runtimes if row.id == status["runtime_id"]), None)
        if entry is None or entry.wheelhouse_sha256 != status["wheelhouse_sha256"]:
            raise ValueError("installed runtime entry differs from runtime state; rerun the plugin's install_runtime.py")
        subprocess.run([str(runtime_python), "-m", "pip", "check"], check=True, env={**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"})
        _verify_release(release, entry)
        _write_launcher(root)
        return status
    finally:
        shutil.rmtree(operation_lock, ignore_errors=True)


def uninstall_runtime(*, home: Path | None = None, accept: bool = False, input_fn: Callable[[str], str] = input) -> dict[str, Any]:
    root = (home or state_root()).resolve()
    targets = [root / "bin", root / "releases", root / "cache", root / "runtime.json"]
    if not accept and input_fn("Remove runtime, launchers, and wheel cache (strategies/catalog/runs remain)? Type 'yes': ").strip().lower() != "yes":
        raise ValueError("runtime uninstall was not accepted")
    root.mkdir(parents=True, exist_ok=True)
    operation_lock = _acquire_install_lock(root, "uninstall")
    try:
        for target in targets:
            if target.is_dir():
                shutil.rmtree(target)
            elif target.exists():
                target.unlink()
    finally:
        shutil.rmtree(operation_lock, ignore_errors=True)
    return {"removed": [str(path) for path in targets], "preserved": [str(root / name) for name in ("strategies", "catalog", "runs")]}


def _validate_origins(entry: RuntimeEntry) -> None:
    for wheel in entry.wheels:
        parsed = urllib.parse.urlsplit(wheel.url)
        origin = (parsed.scheme, parsed.hostname, parsed.port)
        expected = NAUTILUS_ORIGIN if wheel.distribution == "nautilus-trader" else PYPI_ORIGIN
        if origin != expected:
            source = expected[1]
            raise ValueError(f"runtime wheel {wheel.distribution} must use {source}")


def _source_hosts(entry: RuntimeEntry) -> str:
    return ", ".join(sorted({str(urllib.parse.urlsplit(wheel.url).hostname) for wheel in entry.wheels}))


def _install_plan(root: Path, entry: RuntimeEntry, wheelhouse: Path | None) -> list[tuple[Wheel, str]]:
    cache = root / "cache" / "wheels" / entry.id
    plan: list[tuple[Wheel, str]] = []
    for wheel in entry.wheels:
        if _valid_file(cache / wheel.filename, wheel):
            plan.append((wheel, "cache"))
            continue
        local = wheelhouse / wheel.filename if wheelhouse else None
        if local is not None and local.exists():
            if not _valid_file(local, wheel):
                raise ValueError(f"RUNTIME_INTEGRITY_FAILED: {wheel.filename}")
            plan.append((wheel, "local"))
        else:
            plan.append((wheel, "download"))
    return plan


def _format_install_plan(root: Path, entry: RuntimeEntry, plan: list[tuple[Wheel, str]]) -> str:
    lines = [
        f"Research runtime: {entry.id}",
        "Native code will be installed into an isolated local environment.",
        f"State directory: {root}",
    ]
    labels = {"installed": "Installed release", "cache": "Cache hits", "local": "Local wheelhouse"}
    for kind in ("installed", "cache", "local"):
        wheels = [wheel for wheel, source in plan if source == kind]
        lines.append(f"{labels[kind]} ({len(wheels)} files, {sum(wheel.bytes for wheel in wheels)} bytes):")
        lines.extend(f"  - {wheel.filename}" for wheel in wheels)
    downloads = [wheel for wheel, source in plan if source == "download"]
    lines.append(f"Downloads (maximum {sum(wheel.bytes for wheel in downloads)} bytes):")
    by_host: dict[str, list[Wheel]] = {}
    for wheel in downloads:
        by_host.setdefault(str(urllib.parse.urlsplit(wheel.url).hostname), []).append(wheel)
    if not by_host:
        lines.append("  - none")
    for host, wheels in sorted(by_host.items()):
        lines.append(f"  - {host}: {len(wheels)} files, {sum(wheel.bytes for wheel in wheels)} bytes")
        lines.extend(f"    - {wheel.filename}" for wheel in wheels)
    return "\n".join(lines)


def _matching_python(version: str) -> Path:
    if platform.python_implementation() == "CPython" and f"{sys.version_info.major}.{sys.version_info.minor}" == version:
        return Path(sys.executable)
    candidates = [[f"python{version}"]] if os.name != "nt" else [["py", f"-{version}"]]
    for candidate in candidates:
        try:
            output = subprocess.check_output([*candidate, "-c", "import platform,sys;print(platform.python_implementation(),f'{sys.version_info.major}.{sys.version_info.minor}',sys.executable)"], text=True, timeout=10).strip().split(" ", 2)
            if output[:2] == ["CPython", version]:
                return Path(output[2])
        except (OSError, subprocess.SubprocessError):
            pass
    raise ValueError(f"matching CPython {version} is required")


def _acquire_install_lock(root: Path, release_id: str) -> Path:
    lock_dir = root / "install.lock"
    deadline = time.monotonic() + 30
    while True:
        try:
            lock_dir.mkdir()
            _atomic_json(lock_dir / "owner.json", {"pid": os.getpid(), "started_at": int(time.time()), "release_id": release_id})
            return lock_dir
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise ValueError("runtime install is locked; use runtime repair --break-install-lock after verifying the owner stopped")
            time.sleep(0.1)


def _obtain_wheel(
    wheel: Wheel,
    destination: Path,
    local: Path | None,
    progress: Callable[[int, int], None] | None = None,
) -> None:
    if _valid_file(destination, wheel):
        if progress:
            progress(wheel.bytes, wheel.bytes)
        return
    destination.unlink(missing_ok=True)
    partial = destination.with_suffix(destination.suffix + ".partial")
    if local is not None:
        if not local.is_file():
            raise ValueError(f"locked wheel is missing: {local.name}")
        partial.unlink(missing_ok=True)
        shutil.copyfile(local, partial)
        if progress:
            progress(wheel.bytes, wheel.bytes)
    else:
        _download(wheel, partial, progress=progress)
    if not _valid_file(partial, wheel):
        partial.unlink(missing_ok=True)
        raise ValueError(f"RUNTIME_INTEGRITY_FAILED: {wheel.filename}")
    os.replace(partial, destination)


def _download(wheel: Wheel, destination: Path, *, progress: Callable[[int, int], None] | None = None) -> None:
    origin = urllib.parse.urlsplit(wheel.url)
    class SameOrigin(urllib.request.HTTPRedirectHandler):
        redirects = 0
        def redirect_request(self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str) -> Any:
            self.redirects += 1
            target = urllib.parse.urlsplit(newurl)
            if (
                self.redirects > 3
                or target.username
                or target.password
                or target.query
                or target.fragment
                or (target.scheme, target.hostname, target.port) != (origin.scheme, origin.hostname, origin.port)
            ):
                raise ValueError("runtime download redirected outside its locked origin")
            return super().redirect_request(req, fp, code, msg, headers, newurl)
    opener = urllib.request.build_opener(SameOrigin())
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            offset = destination.stat().st_size if destination.is_file() else 0
            if offset >= wheel.bytes:
                destination.unlink(missing_ok=True)
                offset = 0
            headers = {"User-Agent": DOWNLOAD_USER_AGENT}
            if offset:
                headers["Range"] = f"bytes={offset}-"
                if wheel.etag:
                    headers["If-Range"] = wheel.etag
            request = urllib.request.Request(wheel.url, headers=headers)
            with opener.open(request, timeout=15) as response:
                _set_read_timeout(response, 300)
                status = getattr(response, "status", response.getcode())
                mode = "wb"
                expected_bytes = wheel.bytes
                if offset and status == 206:
                    content_range = response.headers.get("Content-Range")
                    if content_range != f"bytes {offset}-{wheel.bytes - 1}/{wheel.bytes}" or (wheel.etag and response.headers.get("ETag") != wheel.etag):
                        destination.unlink(missing_ok=True)
                        continue
                    mode = "ab"
                    expected_bytes = wheel.bytes - offset
                elif offset and status == 200:
                    # The origin ignored Range. Its full response is safe only after
                    # truncating the stale partial and applying all full-body checks.
                    offset = 0
                elif status != 200:
                    raise ValueError(f"runtime download returned unexpected HTTP status {status}")
                length = response.headers.get("Content-Length")
                if length is not None and int(length) != expected_bytes:
                    raise ValueError("runtime Content-Length differs from lock")
                count = offset
                last_report = count
                if progress:
                    progress(count, wheel.bytes)
                with destination.open(mode) as output:
                    while chunk := response.read(min(1024 * 1024, wheel.bytes - count + 1)):
                        count += len(chunk)
                        if count > wheel.bytes:
                            raise ValueError("runtime response exceeds locked size")
                        output.write(chunk)
                        if progress and (count - last_report >= 8 * 1024 * 1024 or count == wheel.bytes):
                            progress(count, wheel.bytes)
                            last_report = count
                if count != wheel.bytes:
                    raise OSError(f"runtime response ended at {count} of {wheel.bytes} bytes")
            return
        except urllib.error.HTTPError as error:
            destination.unlink(missing_ok=True)
            if error.code == 403:
                raise ValueError(
                    "runtime download failed: HTTP 403 (Cloudflare error code 1010). "
                    "Retry the locked URL with curl -A 'Mozilla/5.0' (Windows: curl.exe); "
                    "do not install nautilus_trader from PyPI"
                ) from error
            last_error = error
        except OSError as error:
            # Preserve a bounded partial only for a retryable transport failure.
            if destination.is_file() and destination.stat().st_size >= wheel.bytes:
                destination.unlink(missing_ok=True)
            last_error = error
        except ValueError as error:
            destination.unlink(missing_ok=True)
            last_error = error
    raise ValueError(f"runtime download failed: {last_error}")


def _set_read_timeout(response: Any, timeout: int) -> None:
    """Best-effort urllib split: connect uses opener timeout, reads use 300s.

    CPython exposes the connected socket through this chain for HTTPResponse. If
    a different handler does not, the original 15-second timeout remains, which
    is stricter and never weakens the safety contract.
    """
    try:
        response.fp.raw._sock.settimeout(timeout)
    except AttributeError:
        pass


def _valid_file(path: Path, wheel: Wheel) -> bool:
    if not path.is_file() or path.stat().st_size != wheel.bytes:
        return False
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest() == wheel.sha256


def _core_source(root: Path) -> Path:
    packaged = root / "core_src" / "edgepilot_core"
    if packaged.is_dir():
        return packaged
    checkout = root.parent / "edgepilot-core" / "src" / "edgepilot_core"
    is_source_checkout = (root / "ui" / "package.json").is_file() and (root.parent / "ARCHITECTURE.md").is_file()
    return checkout if is_source_checkout and checkout.is_dir() else packaged


def _plugin_digest(root: Path) -> str:
    digest = hashlib.sha256()
    fixed = (".codex-plugin/plugin.json", ".claude-plugin/plugin.json", "runtime-lock.json", "pyproject.toml", "README.md", "LICENSE", "THIRD_PARTY_NOTICES.md", "DATA_SOURCES.md")
    for relative in fixed:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"plugin is missing {relative}")
        digest.update(relative.encode() + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    for tree in ("src", "core_src", "bundled", "skills", "assets", "licenses"):
        base = root / tree
        prefix = PurePosixPath(tree)
        if tree == "core_src" and not base.exists():
            core = _core_source(root)
            if core.is_dir():
                base = core
                prefix /= "edgepilot_core"
        if not base.exists():
            continue
        for path in sorted(item for item in base.rglob("*") if item.is_file() and "__pycache__" not in item.parts and item.suffix not in {".pyc", ".pyo"}):
            if path.is_symlink():
                raise ValueError("plugin source cannot contain symbolic links")
            name = (prefix / path.relative_to(base).as_posix()).as_posix().encode()
            digest.update(name + b"\0" + hashlib.sha256(path.read_bytes()).digest())
    return digest.hexdigest()


def _copy_app(root: Path, destination: Path) -> None:
    destination.mkdir()
    sources = [
        (root / "src" / "edgepilot_research", destination / "edgepilot_research", "src/edgepilot_research"),
        (_core_source(root), destination / "edgepilot_core", "core_src/edgepilot_core"),
    ]
    for source, target, expected in sources:
        if not source.is_dir():
            raise ValueError(f"plugin is missing {expected}")
        for path in source.rglob("*"):
            if path.is_symlink():
                raise ValueError("plugin app source cannot contain symbolic links")
        shutil.copytree(source, target)
    shutil.copyfile(root / "runtime-lock.json", destination / "runtime-lock.json")


def _plugin_version(root: Path) -> str:
    value = json.loads((root / ".codex-plugin" / "plugin.json").read_text(encoding="utf-8"))
    version = value.get("version")
    if not isinstance(version, str) or not VERSION.fullmatch(version):
        raise ValueError("plugin manifest version is invalid")
    return version


def _venv_python(root: Path) -> Path:
    return root / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def _verify_release(release: Path, entry: RuntimeEntry) -> None:
    python = _venv_python(release / ".venv")
    if not python.is_file():
        raise ValueError("runtime release is missing its Python interpreter")
    expected = json.dumps({wheel.distribution: wheel.version for wheel in entry.wheels}, sort_keys=True)
    code = "import importlib.metadata as m,json; expected=json.loads(" + repr(expected) + "); actual={k:m.version(k) for k in expected}; assert actual==expected,(actual,expected); import edgepilot_research,edgepilot_core,nautilus_trader"
    try:
        subprocess.run([str(python), "-c", code], check=True, env={**os.environ, "PIP_NO_INDEX": "1", "PIP_DISABLE_PIP_VERSION_CHECK": "1"}, stdout=sys.stderr, stderr=sys.stderr)
    except subprocess.CalledProcessError as error:
        raise ValueError("runtime release failed locked-version or import verification") from error


def _write_pth(python: Path, app: Path) -> None:
    site = subprocess.check_output([str(python), "-c", "import site;print(site.getsitepackages()[0])"], text=True).strip()
    relative = os.path.relpath(app.resolve(), Path(site).resolve())
    Path(site, "edgepilot_research_app.pth").write_text(relative + "\n", encoding="utf-8")


def _windows_launcher_content(host: str) -> str:
    if any(ch in host for ch in '"\r\n'):
        raise ValueError("host Python path cannot be written into a cmd launcher")
    return f'@echo off\r\n"{host}" "%~dp0edgepilot-research" %*\r\n'


def _write_launcher(root: Path) -> None:
    bin_dir = root / "bin"
    bin_dir.mkdir(exist_ok=True)
    launcher = bin_dir / "edgepilot-research"
    content = """#!/usr/bin/env python3
import json, os, pathlib, subprocess, sys
home = pathlib.Path(__file__).resolve().parent.parent
try:
    state = json.loads((home / "runtime.json").read_text(encoding="utf-8"))
    relative = pathlib.PurePosixPath(state["active_release"])
    if relative.is_absolute() or ".." in relative.parts or relative.parts[0] != "releases": raise ValueError()
    release = home.joinpath(*relative.parts).resolve()
    if release.parent != (home / "releases").resolve(): raise ValueError()
    python = release / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    if not python.is_file(): raise ValueError()
except Exception:
    print("error: runtime state is invalid; run runtime repair", file=sys.stderr); raise SystemExit(2)
argv = [str(python), "-m", "edgepilot_research.cli", *sys.argv[1:]]
if os.name == "nt":
    raise SystemExit(subprocess.call(argv))
os.execv(str(python), argv)
"""
    _atomic_text(launcher, content)
    launcher.chmod(0o755)
    if os.name == "nt":
        host = str(Path(sys.executable).resolve())
        _atomic_text(bin_dir / "edgepilot-research.cmd", _windows_launcher_content(host))


def launch(argv: list[str] | None = None, *, home: Path | None = None) -> int:
    root = (home or state_root()).resolve()
    state = _read_state(root / "runtime.json", root)
    release = root / state["active_release"]
    python = _venv_python(release / ".venv")
    if not python.is_file():
        raise ValueError("active runtime is incomplete; run runtime repair")
    return subprocess.call([str(python), "-m", "edgepilot_research.cli", *(argv if argv is not None else sys.argv[1:])])


def _atomic_json(path: Path, value: Any) -> None:
    _atomic_text(path, json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def _atomic_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="") as output:
            output.write(value)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)
