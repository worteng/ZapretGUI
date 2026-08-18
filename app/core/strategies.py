"""Встроенные стратегии ZapretGUI.

Каждая стратегия — блок NFQWS2_OPT (мультипрофиль через --new).
Маркер <HOSTLIST> подставляется при записи конфига в зависимости от MODE_FILTER.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass, field
from pathlib import Path

LUA_INIT = "--lua-init=@zapret-lib.lua --lua-init=@zapret-antidpi.lua --lua-init=@zapret-auto.lua"


@dataclass(frozen=True)
class Strategy:
    id: str
    name: str
    description: str
    opt: str
    mode_filter: str = "hostlist"
    tag: str | None = None  # показывается в UI как бейдж


STRATEGIES: list[Strategy] = [
    Strategy(
        id="auto",
        name="Авто",
        description="Сбалансированный набор параметров. Подходит большинству.",
        opt="""--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST> --lua-desync=fake:blob=fake_default_tls:tcp_md5:tcp_seq=-10000:repeats=6:tls_mod=rnd,rndsni,dupsid --lua-desync=multidisorder:pos=1,midsld:seqovl=1 --new
--filter-tcp=80 --filter-l7=http --payload=http_req <HOSTLIST> --lua-desync=fake:blob=fake_default_http:tcp_md5 --lua-desync=multisplit:pos=method+2 --new
--filter-udp=443 --filter-l7=quic --payload=quic_initial <HOSTLIST> --lua-desync=fake:blob=fake_default_quic:repeats=11""",
    ),
    Strategy(
        id="youtube",
        name="YouTube",
        description="Фокус на работу YouTube и видеоплеера.",
        opt="""--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST> --lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=11:tls_mod=rnd,dupsid,sni=www.google.com --lua-desync=multidisorder:pos=1,midsld --new
--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST_NOAUTO> --lua-desync=fake:blob=fake_default_tls:tcp_md5:tcp_seq=-10000:repeats=6 --lua-desync=multidisorder:pos=midsld --new
--filter-tcp=80 --filter-l7=http --payload=http_req <HOSTLIST> --lua-desync=fake:blob=fake_default_http:tcp_md5 --lua-desync=multisplit:pos=method+2 --new
--filter-udp=443 --filter-l7=quic --payload=quic_initial <HOSTLIST> --lua-desync=fake:blob=fake_default_quic:repeats=11 --new""",
    ),
    Strategy(
        id="gaming",
        name="Игровая",
        description="Минимальное вмешательство в трафик. Для игр и низкой нагрузки.",
        opt="""--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST> --lua-desync=multidisorder:pos=1 --new
--filter-tcp=80 --filter-l7=http --payload=http_req <HOSTLIST> --lua-desync=multisplit:pos=method+2 --new
--filter-udp=443 --filter-l7=quic --payload=quic_initial <HOSTLIST> --lua-desync=fake:blob=fake_default_quic:repeats=3 --new""",
    ),
    Strategy(
        id="max-compat",
        name="Максимальная совместимость",
        description="Меньше вмешательства, работает почти везде.",
        opt="""--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST> --lua-desync=fake:blob=fake_default_tls:tcp_md5:repeats=2 --new
--filter-tcp=80 --filter-l7=http --payload=http_req <HOSTLIST> --lua-desync=fake:blob=fake_default_http:tcp_md5 --new
--filter-udp=443 --filter-l7=quic --payload=quic_initial <HOSTLIST> --lua-desync=fake:blob=fake_default_quic:repeats=2 --new""",
    ),
]


def strategy_by_id(strategy_id: str) -> Strategy | None:
    return next((s for s in STRATEGIES if s.id == strategy_id), None)


def _saved_strategies_path() -> Path:
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "zapretgui" / "strategies.json"


def load_saved_strategies() -> list[Strategy]:
    """Пользовательские стратегии из ~/.local/share/zapretgui/strategies.json."""
    path = _saved_strategies_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    result: list[Strategy] = []
    for item in data.get("strategies", []):
        strategy_id = str(item.get("id") or "").strip()
        opt = str(item.get("opt") or "").strip()
        if not strategy_id or not opt:
            continue
        result.append(
            Strategy(
                id=strategy_id,
                name=str(item.get("name") or "Без названия").strip(),
                description=str(item.get("description") or "").strip(),
                opt=opt,
                mode_filter=str(item.get("mode_filter") or "hostlist").strip(),
                tag=str(item.get("tag") or "Моя стратегия").strip() or "Моя стратегия",
            )
        )
    return result


def save_saved_strategy(strategy: Strategy) -> None:
    path = _saved_strategies_path()
    saved = [s for s in load_saved_strategies() if s.id != strategy.id] + [strategy]
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "opt": s.opt,
                "mode_filter": s.mode_filter,
            }
            for s in saved
        ]
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def delete_saved_strategy(strategy_id: str) -> bool:
    saved = load_saved_strategies()
    remaining = [s for s in saved if s.id != strategy_id]
    if len(remaining) == len(saved):
        return False
    path = _saved_strategies_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "strategies": [
            {
                "id": s.id,
                "name": s.name,
                "description": s.description,
                "opt": s.opt,
                "mode_filter": s.mode_filter,
            }
            for s in remaining
        ]
    }
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return True


def new_strategy_id() -> str:
    return "custom-" + uuid.uuid4().hex[:8]


def all_strategies() -> list[Strategy]:
    return STRATEGIES + load_saved_strategies()


def saved_strategy_by_id(strategy_id: str) -> Strategy | None:
    return next((s for s in load_saved_strategies() if s.id == strategy_id), None)


def strategies_as_dict() -> list[dict]:
    return [
        {
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "mode_filter": s.mode_filter,
            "tag": s.tag,
            "builtin": any(b.id == s.id for b in STRATEGIES),
        }
        for s in all_strategies()
    ]


def guess_current_strategy(nfqws2_opt: str) -> str:
    """Пытается определить, какая стратегия сейчас в конфиге."""
    normalized = " ".join(nfqws2_opt.split())
    for s in load_saved_strategies():
        if " ".join(s.opt.split()) == normalized:
            return s.id
    best: tuple[int, str] = (-1, "auto")
    for s in STRATEGIES:
        opt_norm = " ".join(s.opt.split())
        if not opt_norm:
            continue
        match = 0
        for token in set(opt_norm.split()):
            if token in normalized:
                match += 1
        score = match / max(1, len(set(opt_norm.split())))
        if score > best[0]:
            best = (score, s.id)
    return best[1] if best[0] >= 0.55 else "custom"
