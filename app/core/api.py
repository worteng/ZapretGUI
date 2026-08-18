"""JS-мост для pywebview: все операции, вызываемые из веб-интерфейса."""

from __future__ import annotations

import re
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from . import detect, service, strategies, zapret_config

SERVICE_CHECKS = (
    ("YouTube", "https://www.youtube.com"),
    ("Google", "https://www.google.com"),
    ("Discord", "https://discord.com"),
    ("Telegram", "https://web.telegram.org"),
    ("GitHub", "https://github.com"),
)


def _current_config() -> zapret_config.ZapretConfig | None:
    z = detect.detect_zapret()
    if z.config_path is None:
        return None
    return zapret_config.read_config(z.config_path)


def get_state() -> dict:
    system = detect.detect_system()
    zapret = detect.detect_zapret()
    cfg = _current_config()
    current_id = "custom"
    if cfg is not None:
        current_id = strategies.guess_current_strategy(cfg.nfqws2_opt)

    status = _status_of(system, zapret, cfg)

    return {
        "ok": True,
        "system": {
            "distro": system.distro,
            "arch": system.arch,
            "kernel": system.kernel,
            "systemd": system.has_systemd,
            "root": system.is_root,
            "pkexec": system.has_pkexec,
        },
        "zapret": {
            "found": zapret.base_dir is not None,
            "base_dir": str(zapret.base_dir) if zapret.base_dir else None,
            "version": zapret.version,
            "service_active": zapret.service_active,
            "service_enabled": zapret.service_enabled,
            "warnings": zapret.warnings,
            "mode_filter": cfg.mode_filter if cfg else None,
        },
        "status": status,
        "strategy": {
            "id": current_id,
            "name": _strategy_name(current_id),
            "available": strategies.strategies_as_dict(),
            "nfqws2_opt": cfg.nfqws2_opt if cfg else "",
        },
        "ui": {
            "transitions": _ui_transition_desc(),
        },
    }


def _status_of(system: detect.SystemInfo, zapret: detect.ZapretInfo, cfg) -> str:
    if not system.has_systemd:
        return "error"
    if zapret.base_dir is None:
        return "error"
    if zapret.service_active:
        if cfg is None or not cfg.enabled:
            return "degraded"
        return "active"
    return "inactive"


def _strategy_name(strategy_id: str) -> str:
    s = _find_strategy(strategy_id)
    return s.name if s else "Моя стратегия"


def _find_strategy(strategy_id: str):
    return strategies.strategy_by_id(strategy_id) or strategies.saved_strategy_by_id(strategy_id)


def _ui_transition_desc() -> str:
    return "none"


def set_enabled(enabled: bool) -> dict:
    """Включить/выключить защиту. Root через pkexec."""
    if enabled:
        result = service.start()
    else:
        result = service.stop()
    print(f"[zapretgui] set_enabled({enabled}) → {result}", flush=True)
    _update_result_message(result, enabled)
    return result


def _update_result_message(result: dict, enabled: bool) -> None:
    if result.get("ok"):
        result["message"] = "Защита включена" if enabled else "Защита выключена"
    else:
        result["message"] = result.get("error", "Не удалось выполнить операцию")


def apply_strategy(strategy_id: str) -> dict:
    """Применяет стратегию: обновляет config и перезапускает службу.

    Работает как со встроенными, так и с пользовательскими стратегиями.
    """
    strategy = _find_strategy(strategy_id)
    if strategy is None:
        return {"ok": False, "error": f"Неизвестная стратегия: {strategy_id}"}

    z = detect.detect_zapret()
    if z.base_dir is None or z.config_path is None:
        return {"ok": False, "error": "zapret2 не установлен"}

    new_opt = strategy.opt.replace("<HOSTLIST_NOAUTO>", "<HOSTLIST>")
    return _apply_opt(new_opt, strategy.mode_filter, z, strategy.name)


def _apply_opt(opt: str, mode_filter: str, z: detect.ZapretInfo, name: str) -> dict:
    """Записывает опции в config (с бэкапом) и перезапускает службу."""
    cfg = zapret_config.read_config(z.config_path)
    if cfg is None:
        new_raw = zapret_config.build_config(opt, mode_filter)
    else:
        new_raw = zapret_config.replace_opt_and_mode(cfg.raw, opt, mode_filter)

    dry = zapret_config.dry_run_validate(opt, z.base_dir)
    if not dry["ok"]:
        return {
            "ok": False,
            "error": f"Стратегия не прошла проверку: {dry['error']}",
        }

    try:
        saved = _write_config_via_pkexec(z.config_path, new_raw)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": f"Не удалось записать конфигурацию: {e}"}
    if not saved["ok"]:
        return saved

    restart = service.restart()
    if not restart["ok"]:
        return {
            "ok": False,
            "error": f"Стратегия сохранена, но служба не перезапущена: {restart['error']}",
            "strategy_saved": True,
        }

    # небольшая пауза, затем фактический статус
    time.sleep(1.0)
    if not service.service_active():
        return {
            "ok": False,
            "error": "Стратегия применена, но служба не запустилась. Проверьте Логи.",
            "strategy_saved": True,
        }
    return {"ok": True, "message": f"Стратегия «{name}» применена"}


def _tmp_file(content: str) -> Path:
    f = tempfile.NamedTemporaryFile(
        mode="w", prefix="zapretgui-", suffix=".conf", delete=False, encoding="utf-8"
    )
    f.write(content)
    f.close()
    return Path(f.name)


def _write_config_via_pkexec(config_path: Path, new_raw: str) -> dict:
    """Записывает config через pkexec, предварительно делая бэкап."""
    tmp = _tmp_file(new_raw)
    backup_dest = config_path.with_name(
        f"config.backup-gui-{time.strftime('%Y-%m-%d-%H%M%S')}"
    )
    script = (
        f"cp {shlex.quote(str(config_path))} {shlex.quote(str(backup_dest))} && "
        f"install -m 644 {shlex.quote(str(tmp))} {shlex.quote(str(config_path))}"
    )
    cmd = ["pkexec", "sh", "-c", script]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    tmp.unlink(missing_ok=True)
    if p.returncode == 0:
        return {"ok": True}
    if "not authorized" in (p.stderr or "") or "Authentication failure" in (p.stderr or ""):
        return {"ok": False, "error": "Доступ не подтверждён"}
    return {"ok": False, "error": (p.stderr or p.stdout or "").strip() or f"код {p.returncode}"}


def check_services() -> dict:
    """Проверяет доступность сервисов (по списку SERVICE_CHECKS)."""
    curl = shutil.which("curl")
    if curl is None:
        return {"ok": False, "error": "curl не найден"}
    results = []
    for name, url in SERVICE_CHECKS:
        t0 = time.monotonic()
        try:
            p = subprocess.run(
                [
                    curl, "-4", "-s", "-o", "/dev/null", "-w", "%{http_code}",
                    "--connect-timeout", "5", "--max-time", "10", url,
                ],
                capture_output=True,
                text=True,
                timeout=15,
            )
            latency = round(time.monotonic() - t0, 2)
            code = p.stdout.strip()
            ok = p.returncode == 0 and code not in ("000", "")
            results.append({"name": name, "ok": ok, "code": code, "ms": latency})
        except (OSError, subprocess.TimeoutExpired):
            results.append({"name": name, "ok": ok, "code": "timeout", "ms": 0})
    return {"ok": True, "results": results, "time": time.strftime("%H:%M:%S")}


def _validate_opt(opt: str) -> dict:
    """Dry-run валидация опций с попыткой определить номер строки ошибки."""
    z = detect.detect_zapret()
    if z.base_dir is None:
        return {"ok": False, "error": "zapret2 не установлен"}
    result = zapret_config.dry_run_validate(opt, z.base_dir)
    if result.get("ok"):
        return result
    error = str(result.get("error") or "")
    match = re.search(r"\bline\s*[:=]?\s*(\d+)", error, re.IGNORECASE)
    result["line"] = int(match.group(1)) if match else None
    return result


def editor_get(strategy_id: str) -> dict:
    """Данные стратегии для редактора: параметры из конфига или из кода/JSON."""
    strategy_id = str(strategy_id or "")
    cfg = _current_config()
    if strategy_id and strategies.strategy_by_id(strategy_id):
        s = strategies.strategy_by_id(strategy_id)
        return {
            "ok": True,
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "opt": s.opt.replace("<HOSTLIST_NOAUTO>", "<HOSTLIST>"),
            "mode_filter": s.mode_filter,
            "builtin": True,
        }
    if strategy_id and strategies.saved_strategy_by_id(strategy_id):
        s = strategies.saved_strategy_by_id(strategy_id)
        return {
            "ok": True,
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "opt": s.opt,
            "mode_filter": s.mode_filter,
            "builtin": False,
        }
    if cfg is not None and (not strategy_id or strategy_id == "current"):
        s = strategies.guess_current_strategy(cfg.nfqws2_opt)
        saved = strategies.saved_strategy_by_id(s) if not strategies.strategy_by_id(s) else None
        return {
            "ok": True,
            "id": "current",
            "name": saved.name if saved else (_strategy_name(s) if s != "custom" else "Моя стратегия"),
            "description": (saved.description if saved else "") if s != "custom" else "Пользовательская стратегия из текущего конфига.",
            "opt": cfg.nfqws2_opt,
            "mode_filter": cfg.mode_filter,
            "builtin": False,
        }
    return {"ok": False, "error": "Стратегия не найдена"}


def editor_validate(opt: str) -> dict:
    """Проверка параметров из редактора без сохранения."""
    result = _validate_opt(str(opt or ""))
    print(f"[zapretgui] editor_validate → {result}", flush=True)
    return result


def editor_save(payload: dict) -> dict:
    """Сохраняет стратегию (встроенную — как копию) и при необходимости применяет."""
    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    opt = str(payload.get("opt") or "").strip()
    if not opt:
        return {"ok": False, "error": "Опции пустые"}
    mode_filter = str(payload.get("mode_filter") or "hostlist").strip()
    if mode_filter not in zapret_config.MODE_FILTER_CHOICES:
        return {"ok": False, "error": f"Недопустимый MODE_FILTER: {mode_filter}"}

    apply = bool(payload.get("apply", True))
    strategy_id = str(payload.get("id") or "").strip()

    dry = _validate_opt(opt)
    if not dry["ok"]:
        return {"ok": False, "error": f"Стратегия не прошла проверку: {dry['error']}"}

    if not strategy_id or strategies.strategy_by_id(strategy_id):
        source = strategies.strategy_by_id(strategy_id) if strategy_id else None
        strategy_id = strategies.new_strategy_id()
        if not name:
            name = f"Копия: {source.name}" if source else "Моя стратегия"
        if not description and source:
            description = source.description
    elif not strategies.saved_strategy_by_id(strategy_id):
        strategy_id = strategies.new_strategy_id()
        if not name:
            name = "Моя стратегия"

    strategy = strategies.Strategy(
        id=strategy_id,
        name=name or "Моя стратегия",
        description=description,
        opt=opt,
        mode_filter=mode_filter,
        tag="Моя стратегия",
    )
    strategies.save_saved_strategy(strategy)

    if apply:
        z = detect.detect_zapret()
        if z.base_dir is None or z.config_path is None:
            return {"ok": False, "error": "zapret2 не установлен", "id": strategy_id}
        result = _apply_opt(opt, mode_filter, z, strategy.name)
        if not result["ok"]:
            result["id"] = strategy_id
            return result

    print(f"[zapretgui] editor_save({strategy_id}, apply={apply}) → ok", flush=True)
    return {"ok": True, "id": strategy_id, "message": f"Стратегия «{strategy.name}» сохранена"}


def editor_delete(strategy_id: str) -> dict:
    """Удаляет пользовательскую стратегию (встроенные неудаляемы)."""
    strategy_id = str(strategy_id or "")
    if strategies.strategy_by_id(strategy_id):
        return {"ok": False, "error": "Встроенную стратегию нельзя удалить"}
    if not strategies.delete_saved_strategy(strategy_id):
        return {"ok": False, "error": "Стратегия не найдена"}
    print(f"[zapretgui] editor_delete({strategy_id}) → ok", flush=True)
    return {"ok": True, "message": "Стратегия удалена"}


class Api:
    """Мост для pywebview: публичные методы вызываются из JS."""

    def log(self, message: str) -> None:
        """Отладочный лог из JS (пишется в stderr процесса)."""
        print(f"[js] {message}", flush=True)

    def get_state(self) -> dict:
        return get_state()

    def set_enabled(self, enabled: bool) -> dict:
        return set_enabled(enabled)

    def set_enabled_autostart(self, enabled: bool) -> dict:
        if enabled:
            result = service.enable()
        else:
            result = service.disable()
        if result.get("ok"):
            result["message"] = "Автозапуск включён" if enabled else "Автозапуск выключен"
        return result

    def apply_strategy(self, strategy_id: str) -> dict:
        return apply_strategy(strategy_id)

    def check_services(self) -> dict:
        return check_services()

    def editor_get(self, strategy_id: str) -> dict:
        return editor_get(strategy_id)

    def editor_validate(self, opt: str) -> dict:
        return editor_validate(opt)

    def editor_save(self, payload: dict) -> dict:
        return editor_save(payload)

    def editor_delete(self, strategy_id: str) -> dict:
        return editor_delete(strategy_id)