"""Работа с /opt/zapret2/config: чтение, валидация, бэкап, запись."""

from __future__ import annotations

import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path

MODE_FILTER_CHOICES = ("none", "ipset", "hostlist", "autohostlist")


@dataclass
class ZapretConfig:
    path: Path
    raw: str
    variables: dict[str, str]
    nfqws2_opt: str = ""
    mode_filter: str = "hostlist"
    enabled: bool = True

    @property
    def name(self) -> str:
        return self.path.name


def read_config(config_path: Path) -> ZapretConfig | None:
    if not config_path.is_file():
        return None
    try:
        raw = config_path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    cfg = ZapretConfig(path=config_path, raw=raw, variables=_parse_vars(raw))
    cfg.nfqws2_opt = cfg.variables.get("NFQWS2_OPT", "")
    cfg.mode_filter = cfg.variables.get("MODE_FILTER", "hostlist").strip()
    cfg.enabled = cfg.variables.get("NFQWS2_ENABLE", "1").strip() != "0"
    return cfg


def _parse_vars(raw: str) -> dict[str, str]:
    vars_: dict[str, str] = {}
    current_key: str | None = None
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        # продолжение многострочного значения начинается с пробела/таба
        if line[:1] in (" ", "\t") and current_key is not None:
            vars_[current_key] += "\n" + line
            continue
        current_key = None
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not key.isidentifier():
            continue
        vars_[key] = value.strip()
        current_key = key
    return vars_


def backup_config(cfg: ZapretConfig) -> Path:
    stamp = time.strftime("%Y-%m-%d-%H%M%S")
    backup = cfg.path.with_name(f"config.backup-{stamp}")
    backup.write_text(cfg.raw, encoding="utf-8")
    return backup


def build_config(opt: str, mode_filter: str, extra: dict[str, str] | None = None) -> str:
    """Собирает минимальный валидный config вокруг стратегии.

    Сохраняет только те переменные, которые нужны стандартному режиму;
    остальные (листы, ipsets, autohostlist) берут значения по умолчанию.
    """
    if mode_filter not in MODE_FILTER_CHOICES:
        raise ValueError(f"Недопустимый MODE_FILTER: {mode_filter}")
    lines = [
        "NFQWS2_ENABLE=1",
        f"NFQWS2_OPT=\n{_indent(opt)}\n",
        f"MODE_FILTER={mode_filter}",
        "NFQWS2_PORTS_TCP=80,443",
        "NFQWS2_PORTS_UDP=443",
        "NFQWS2_TCP_PKT_OUT=20",
        "NFQWS2_TCP_PKT_IN=10",
        "NFQWS2_UDP_PKT_OUT=5",
        "NFQWS2_UDP_PKT_IN=3",
        "INIT_APPLY_FW=1",
        "DISABLE_IPV6=1",
        "FILTER_TTL_EXPIRED_ICMP=1",
        "FLOWOFFLOAD=donttouch",
        "GZIP_LISTS=1",
        "",
    ]
    if extra:
        for k, v in extra.items():
            lines.append(f"{k}={v}")
    return "\n".join(lines)


def _indent(multiline: str) -> str:
    return "\n".join(f"  {line}" if line else line for line in multiline.splitlines())


def write_config(cfg: ZapretConfig, new_raw: str) -> Path:
    backup = backup_config(cfg)
    cfg.path.write_text(new_raw, encoding="utf-8")
    cfg.raw = new_raw
    cfg.variables = _parse_vars(new_raw)
    cfg.nfqws2_opt = cfg.variables.get("NFQWS2_OPT", "")
    return backup


def replace_opt_and_mode(raw: str, new_opt: str, mode_filter: str) -> str:
    """Заменяет блок NFQWS2_OPT и MODE_FILTER в существующем config.

    Блок NFQWS2_OPT многострочен: продолжается строками с ведущими
    пробелами/табами. Остальные настройки (листы, autohostlist) сохраняются.
    """
    if mode_filter not in MODE_FILTER_CHOICES:
        raise ValueError(f"Недопустимый MODE_FILTER: {mode_filter}")

    lines = raw.splitlines()
    out: list[str] = []
    i = 0
    replaced_opt = False
    while i < len(lines):
        line = lines[i]
        if line.lstrip().startswith("NFQWS2_OPT="):
            i += 1
            while i < len(lines) and lines[i].startswith((" ", "\t")):
                i += 1
            out.append("NFQWS2_OPT=")
            out.extend("  " + ln if ln else ln for ln in new_opt.splitlines())
            replaced_opt = True
            continue
        if line.lstrip().startswith("MODE_FILTER="):
            out.append(f"MODE_FILTER={mode_filter}")
            i += 1
            continue
        out.append(line)
        i += 1

    result = "\n".join(out)
    if not replaced_opt:
        result = result + "\nNFQWS2_OPT=\n" + _indent(new_opt) + "\n"
    return result


def dry_run_validate(opt: str, zapret_dir: Path | None) -> dict:
    """Проверяет опции стратегии через nfqws2 --dry-run (без root не всегда)."""
    if zapret_dir is None:
        return {"ok": False, "error": "zapret2 не найден"}
    import platform
    import tempfile

    candidates = [
        zapret_dir / "binaries" / f"linux-{platform.machine()}" / "nfqws2",
        zapret_dir / "nfq2" / "nfqws2",
    ]
    binary = next((p for p in candidates if p.is_file()), None)
    if binary is None:
        return {"ok": False, "error": "бинарник nfqws2 не найден"}

    with tempfile.NamedTemporaryFile(
        mode="w", prefix="zapretgui-dryrun-", suffix=".conf", delete=False, encoding="utf-8"
    ) as f:
        lua_dir = zapret_dir / "lua"
        header = " ".join(
            f"--lua-init=@{lua_dir / name}"
            for name in ("zapret-lib.lua", "zapret-antidpi.lua", "zapret-auto.lua")
            if (lua_dir / name).is_file()
        )
        lines = "\n".join(
            f"{header} {line}" if not line.lstrip().startswith("--lua-init") else line
            for line in opt.splitlines()
        )
        f.write(lines)
        tmp = Path(f.name)
    cmd = [str(binary), "--dry-run", f"@{tmp}"] + ["--qnum=300"] + shlex.split(header)
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=15,
        )
        if p.returncode == 0:
            return {"ok": True}
        detail = (p.stderr or p.stdout or "").strip().splitlines()
        return {"ok": False, "error": detail[-1] if detail else f"код {p.returncode}"}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"ok": False, "error": str(e)}
    finally:
        tmp.unlink(missing_ok=True)
