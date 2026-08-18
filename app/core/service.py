"""Управление службой zapret2 через systemd (root-операции через pkexec)."""

from __future__ import annotations

import shutil
import subprocess
from typing import Callable

from .detect import SERVICE_NAME

_ESCAPE = set("\\'\"` $&|;<>()")


def _shell_quote(s: str) -> str:
    if not s or any(c in _ESCAPE for c in s):
        return "'" + s.replace("'", "'\\''") + "'"
    return s


def _pkexec_cmd(args: list[str]) -> list[str]:
    return ["pkexec"] + args


def _run(args: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def service_active() -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        out = _run(["systemctl", "is-active", SERVICE_NAME])
        return out.stdout.strip() == "active"
    except (OSError, subprocess.TimeoutExpired):
        return False


def service_enabled() -> bool:
    if shutil.which("systemctl") is None:
        return False
    try:
        out = _run(["systemctl", "is-enabled", SERVICE_NAME])
        return out.stdout.strip() in ("enabled", "enabled-runtime")
    except (OSError, subprocess.TimeoutExpired):
        return False


def start(on_password: Callable[[], None] | None = None) -> dict:
    return _control(["systemctl", "start", SERVICE_NAME], on_password)


def stop(on_password: Callable[[], None] | None = None) -> dict:
    return _control(["systemctl", "stop", SERVICE_NAME], on_password)


def restart(on_password: Callable[[], None] | None = None) -> dict:
    return _control(["systemctl", "restart", SERVICE_NAME], on_password)


def enable(on_password: Callable[[], None] | None = None) -> dict:
    return _control(["systemctl", "enable", SERVICE_NAME], on_password)


def disable(on_password: Callable[[], None] | None = None) -> dict:
    return _control(["systemctl", "disable", SERVICE_NAME], on_password)


def _control(base_args: list[str], on_password: Callable[[], None] | None) -> dict:
    args = list(base_args)
    if on_password is not None:
        on_password()
    if os_geteuid() != 0:
        if shutil.which("pkexec") is None:
            return {"ok": False, "error": "pkexec не найден, невозможно запросить права"}
        args = _pkexec_cmd(args)
    try:
        p = _run(args)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"Не удалось выполнить команду: {e}"}
    if p.returncode == 0:
        return {"ok": True}
    stderr = (p.stderr or "").strip()
    if "not authorized" in stderr or "Authentication failure" in stderr:
        return {"ok": False, "error": "Доступ не подтверждён"}
    return {"ok": False, "error": stderr or f"Код ошибки {p.returncode}"}


def os_geteuid() -> int:
    import os

    return os.geteuid()
