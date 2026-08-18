"""Обнаружение системы и zapret2."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

KNOWN_ZAPRET_PATHS = (
    Path("/opt/zapret2"),
    Path("/usr/local/zapret2"),
)

SERVICE_NAME = "zapret2.service"
DAEMON_PIDFILE = Path("/var/run/nfqws2_1.pid")


@dataclass
class SystemInfo:
    distro: str
    distro_id: str
    arch: str
    python_version: str
    has_systemd: bool = False
    has_pkexec: bool = False
    is_root: bool = False
    kernel: str = ""


@dataclass
class ZapretInfo:
    base_dir: Path | None = None
    version: str | None = None
    config_path: Path | None = None
    daemon_path: Path | None = None
    daemon_pid: int | None = None
    service_active: bool = False
    service_enabled: bool = False
    config_backup_count: int = 0
    warnings: list[str] = field(default_factory=list)


def detect_system() -> SystemInfo:
    info = SystemInfo(
        distro=_distro_name(),
        distro_id=_distro_id(),
        arch=platform.machine(),
        python_version=platform.python_version(),
        kernel=platform.release(),
    )
    info.is_root = os.geteuid() == 0
    info.has_systemd = _has_systemd()
    info.has_pkexec = shutil.which("pkexec") is not None
    return info


def _distro_name() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("PRETTY_NAME="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return platform.system()


def _distro_id() -> str:
    try:
        with open("/etc/os-release", encoding="utf-8") as f:
            for line in f:
                if line.startswith("ID="):
                    return line.split("=", 1)[1].strip().strip('"')
    except OSError:
        pass
    return "unknown"


def _has_systemd() -> bool:
    return Path("/run/systemd/system").is_dir() or (
        shutil.which("systemctl") is not None
        and subprocess.run(
            ["systemctl", "--version"],
            capture_output=True,
        ).returncode == 0
    )


def find_zapret_base() -> Path | None:
    env = os.environ.get("ZAPRETGUI_ZAPRET_DIR")
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    for p in KNOWN_ZAPRET_PATHS:
        if p.is_dir():
            return p
    return None


def _daemon_binary(base: Path) -> Path | None:
    variants = (
        base / "binaries" / f"linux-{platform.machine()}" / "nfqws2",
        base / "binaries" / f"linux-{platform.machine().replace('x86_64', 'x86_64')}" / "nfqws2",
        base / "nfq2" / "nfqws2",
    )
    for v in variants:
        if v.is_file() and os.access(v, os.X_OK):
            return v
    for pattern in ("nfqws2*", "nfq2*"):
        for v in base.glob(pattern):
            if v.is_file() and os.access(v, os.X_OK) and v.name in ("nfqws2", "nfq2"):
                return v
    return None


def detect_zapret() -> ZapretInfo:
    info = ZapretInfo()
    base = find_zapret_base()
    if base is None:
        info.warnings.append("zapret2 не найден в известных путях")
        return info
    info.base_dir = base
    info.config_path = base / "config"
    info.daemon_path = _daemon_binary(base)
    info.version = _read_version(info.daemon_path)
    info.daemon_pid = _read_pid()
    info.service_active = _systemctl_is_active(SERVICE_NAME)
    info.service_enabled = _systemctl_is_enabled(SERVICE_NAME)
    if info.config_path.is_file():
        info.config_backup_count = len(list(base.glob("config.*")))

    stale_timer = (
        shutil.which("systemctl")
        and _systemctl_is_active("zapret-list-update.timer")
    )
    own_timer = _systemctl_is_active("zapret2-list-update.timer")
    if stale_timer and not own_timer:
        info.warnings.append(
            "Обнаружен устаревший таймер обновления списков от zapret1 "
            "(zapret-list-update.timer). Родной таймер zapret2 выключен."
        )
    return info


def _read_version(daemon: Path | None) -> str | None:
    if daemon is None:
        return None
    try:
        out = subprocess.run(
            [str(daemon), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        text = (out.stdout or out.stderr or "").strip()
        if not text:
            return None
        parts = text.split()
        for p in parts:
            if p.startswith("v") and len(p) > 1 and p[1].isdigit():
                return p
        return text.splitlines()[0]
    except (OSError, subprocess.TimeoutExpired):
        return None


def _read_pid() -> int | None:
    try:
        return int(DAEMON_PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return None


def _systemctl_is_active(unit: str) -> bool:
    return _systemctl_check(unit, "is-active")


def _systemctl_is_enabled(unit: str) -> bool:
    return _systemctl_check(unit, "is-enabled")


def _systemctl_check(unit: str, sub: str) -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        out = subprocess.run(
            ["systemctl", sub, unit],
            capture_output=True,
            text=True,
            timeout=5,
        )
        value = (out.stdout or "").strip()
        if sub == "is-active":
            # Точное сравнение: "inactive" содержит подстроку "active"!
            return value == "active"
        return value in ("enabled", "enabled-runtime")
    except (OSError, subprocess.TimeoutExpired):
        return False
