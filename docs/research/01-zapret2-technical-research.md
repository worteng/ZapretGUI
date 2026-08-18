# ZapretGUI — Phase 0: Technical Research

Дата: 18.08.2026
Статус: завершено
Автор: ZapretGUI research (описание системы проверено на реальном установленном zapret2 1.0.4 на Arch Linux)

Источники:
- Официальная документация zapret2: `zapret2-readme.md`, `zapret2-manual.md` (в этой директории)
- `zapret2-config.default` (в этой директории)
- Реальная установка `zapret2-bin 1.0.4-1` на /opt/zapret2 (Arch Linux)
- https://github.com/bol-van/zapret2

---

## 1. Что такое zapret2

**zapret2** (bol-van/zapret2, ~5.2k stars на момент исследования) — дальнейшее развитие проекта [zapret](https://github.com/bol-van/zapret) (далее zapret1). Автономное средство противодействия DPI, не требующее сторонних серверов.

Ключевое отличие от zapret1: **стратегии обхода DPI больше не зашиты в C-код**, они реализованы на **Lua** и являются «программно-управляемыми» (`--lua-desync`). Движок `nfqws2` распознаёт протоколы, реассемблирует, дешифрует, управляет профилями/хостлистами/ipsets, но само «дурение» DPI выполняет Lua-код.

Это принципиально важно для GUI: **стратегия — это данные (параметры командной строки), а не отдельный бинарник**. Стратегии можно генерировать, подставлять, тестировать и менять без пересборки.

Официальная позиция автора: zapret2 — инструмент для энтузиастов, «не готовое решение для чайников». Именно нишу «готового решения для чайников» и занимает ZapretGUI.

---

## 2. Архитектура (Linux)

```
Трафик (ядро)
    │
    ▼
nftables/iptables (правила перехвата, очередь NFQUEUE 300)
    │
    ▼
nfqws2  (--user=zapret2, sбрасывает привилегии после старта)
    │
    ├─ C-ядро: фильтрация по портам/L7, реассемблинг, диссекты (как in wireshark),
    │           payload-типы (tls_client_hello, http_req, quic_initial...), хостлисты, ipsets
    │
    └─ Lua-движок: zapret-lib.lua (хелперы) + zapret-antidpi.lua (библиотека стратегий)
                  + zapret-auto.lua (автостратегии/оркестрация, autohostlist)
```

### Компоненты

| Компонент | Назначение |
|---|---|
| `nfqws2` | основной демон (Linux/Mac: перехват через NFQUEUE; Windows: др. движок winws2) |
| `mdig` | параллельный DNS-резолвер (30 потоков по умолч.) для превращения хостлистов в IP-листы |
| `ip2net` | агрегация списков IP в подсети (v4: prefix 22-30, v6: 56-64) для сокращения размера сетов |

### Стандартный режим запуска

`NFQWS2_OPT` из config + служебные опции, добавляемые автоматически:

```
nfqws2 --qnum=300 --fwmark=0x40000000 --user=zapret2 \
  --lua-init=@zapret-lib.lua --lua-init=@zapret-antidpi.lua --lua-init=@zapret-auto.lua \
  <NFQWS2_OPT с подставленными <HOSTLIST>>
```

`NFQWS2_OPT` — мультистратегия: несколько профилей, разделённых `--new`. Каждый профиль имеет свои фильтры (`--filter-tcp/udp`, `--filter-l7`, `--payload`, `--in-range`/`--out-range`, `--hostlist`/`--hostlist-exclude`) и список `--lua-desync` функций.

### Текущий рабочий конфиг на машине (3 профиля)

1. **TLS 443**: `--filter-tcp=443 --filter-l7=tls --payload=tls_client_hello <HOSTLIST> --lua-desync=fake:blob=fake_default_tls:tcp_md5:tcp_seq=-10000:repeats=6:tls_mod=rnd,rndsni,dupsid --lua-desync=multidisorder:pos=1,midsld:seqovl=1 --new`
2. **HTTP 80**: `--filter-tcp=80 --filter-l7=http --payload=http_req <HOSTLIST> --lua-desync=fake:blob=fake_default_http:tcp_md5 --lua-desync=multisplit:pos=method+2 --new`
3. **QUIC 443/UDP**: `--filter-udp=443 --filter-l7=quic --payload=quic_initial <HOSTLIST> --lua-desync=fake:blob=fake_default_quic:repeats=11`

---

## 3. Перехват трафика (firewall backend)

### nftables (основной, десктопный Linux)

- Таблица `inet zapret2`, очередь **NFQUEUE 300** (`QNUM`), `queue ... bypass`.
- **POSTNAT по умолчанию** (`POSTNAT=1`): исходящие перехватываются в hook `postrouting`, входящие — в `prerouting`.
- Ограничение первых пакетов соединения через `ct original packets 1-N` / `ct reply packets 1-N` (аналог connbytes; N из `NFQWS2_TCP_PKT_OUT/IN`, `NFQWS2_UDP_PKT_OUT/IN`).
- **Защита от петли**: пакеты, сгенерированные nfqws2, помечаются `--fwmark=0x40000000` (DESYNC_MARK); правила jump'ят в цепочку перехвата только при `meta mark and 0x40000000 == 0`. В POSTNAT добавлен второй марк `0x20000000` + правило `notrack` в цепочке output (иначе conntrack роняет сгенерированные пакеты как INVALID).
- Сеты (`type ipv4_addr; flags interval`): `zapret`, `zapret6` (включающие, только при `MODE_FILTER=ipset`), `ipban`, `ipban6` (заворот трафика), `nozapret`, `nozapret6` (исключающие, применяются всегда), сеты интерфейсов `wanif/wanif6/lanif`.
- `FILTER_TTL_EXPIRED_ICMP=1`: для помеченных десинком потоков дропаются ICMP/ICMPv6 time-exceeded (защита от «сбоев» маршрутизации фейков) — работает через CONNMARK только в POSTNAT.
- `FLOWOFFLOAD`: `donttouch` (десктоп) / `software` / `hardware` (роутеры, требует указания IFACE_*).
- `IFACE_WAN/IFACE_WAN6/IFACE_LAN`: если не заданы — перехват действует на всех интерфейсах (типично для десктопа).

### iptables (fallback)

Старые ядра: mangle POSTROUTING (или INPUT/FORWARD), `-m connbytes ... 1:20`, марк-фильтры, ipsets портов (`bitmap:port zport_tcp...`) и сетей. Перехват только до NAT.

### Выбор backend

`common/fwtype.sh`: nftables, если есть `nft` и ядро ≥ 4.16, иначе iptables. Переопределяется `FWTYPE=`.

### Что это значит для ZapretGUI

- **Firewall не трогаем вручную** — правилами управляет `init.d/sysv/zapret2 start-fw/stop-fw` (или целиком start/stop).
- GUI должен лишь держать в порядке `config` (порты, PKT_OUT/IN, MODE_FILTER, IP2NET_OPT...) и вызывать скрипты.
- Отдельный «Firewall Backend» в архитектуре GUI = тонкая обёртка над этими скриптами.

---

## 4. Управление: скрипты и systemd

### sysv init скрипт `/opt/zapret2/init.d/sysv/zapret2`

Команды (все требуют root):

```
start | stop | restart
start-fw | stop-fw | restart-fw
start-daemons | stop-daemons | restart-daemons
reload-ifsets | list-ifsets | list-table
```

Логика start: 1) `zapret_run_daemons` (запуск nfqws2 в фоне, pidfile `/var/run/nfqws2_1.pid`); 2) `zapret_apply_firewall` (если `INIT_APPLY_FW=1`).

### systemd (Arch-пакет)

- `zapret2.service` — `Type=forking`, ExecStart = sysv-скрипт `start`, ExecStop = `stop`. **Эту службу использует GUI для ON/OFF.**
- `zapret2-list-update.service` + `zapret2-list-update.timer` — обновление списков раз в 2 суток в случайное время (в установленной системе выключен, см. § 11).
- `nfqws2@.service` — альтернативный шаблон для ручного управления без скриптов (требует сборки с `make systemd` и конфигов в `/etc/zapret2`; в bin-пакете непригоден). **GUI его не использует.**

### Авторизация

Все операции управления — root. Для GUI обязательно: **pkexec/polkit** (или sudo), пароль не хранить (план §23).

---

## 5. Файл config

`/opt/zapret2/config` (не /etc!) — shell include с переменными. Его же читают скрипты ipset. Это **единственный файл, с которым работает GUI** (стратегии, порты, режимы).

Полная таблица переменных из мануала:

| Переменная | Назначение |
|---|---|
| `TMPDIR` | временная директория (мало памяти) |
| `WS_USER` | пользователь демона (auto) |
| `FWTYPE` | iptables/nftables/ipfw (auto) |
| `SET_MAXELEM`, `IPSET_OPT` | размеры/параметры сетов |
| `IPSET_HOOK` | кастомный поставщик IP в сеты |
| `IP2NET_OPT4/6` | агрегация IP-листов в подсети |
| `MDIG_THREADS/EAGAIN/EAGAIN_DELAY` | DNS-резолвер |
| `AUTOHOSTLIST_*` | детектор неудач (autohostlist) |
| `GZIP_LISTS` | gzip генерируемых листов |
| `DESYNC_MARK`, `DESYNC_MARK_POSTNAT` | марк-биты |
| `FILTER_MARK` | перехват только с этим битом (спецфильтры) |
| `POSTNAT` | перехват после NAT (nft, def 1) |
| `NFQWS2_ENABLE` | вкл/выкл демон |
| `NFQWS2_PORTS_TCP/UDP` | порты перехвата |
| `NFQWS2_TCP_PKT_OUT/IN`, `NFQWS2_UDP_PKT_OUT/IN` | ограничители первых пакетов |
| `NFQWS2_PORTS_*_KEEPALIVE` | порты без ограничителя |
| `NFQWS2_OPT` | **сама стратегия** |
| `MODE_FILTER` | none/ipset/hostlist/autohostlist |
| `FLOWOFFLOAD` | donttouch/none/software/hardware |
| `IFACE_LAN/WAN/WAN6` | интерфейсы (классический Linux) |
| `OPENWRT_LAN/WAN4/WAN6` | интерфейсы netifd (OpenWrt) |
| `INIT_APPLY_FW` | применять firewall в start/stop |
| `INIT_FW_*_HOOK` | хуки до/после поднятия/опускания |
| `DISABLE_IPV4/6` | отключить семейство |
| `FILTER_TTL_EXPIRED_ICMP` | фильтр ICMP time-exceeded |
| `GETLIST` | какой лист-скрипт запускать (def get_ipban.sh) |

### Маркеры в NFQWS2_OPT

- `<HOSTLIST>` — подставляется как `--hostlist=<user> --hostlist=<main>` (+ `--hostlist-exclude`) или **пусто при MODE_FILTER=none** (десинк всего на 80/443 — опасно).
- `<HOSTLIST_NOAUTO>` — то же без авто-листа.
- Прямые пути в `--hostlist` **запрещены** (check_bad_ws_options ругается; ломает MODE_FILTER).

---

## 6. Стратегии

### Формат

`--filter-*` (что перехватывать) + `--payload` (какой пейлоад) + `--lua-desync=<функция>:<параметры>`. Профили в одной мультистратегии разделяются `--new`.

Основные функции из `zapret-antidpi.lua`: `fake`, `fakedsplit`, `multidisorder`, `multisplit`, `pktmod`, `syndata`, `wssize`, `tcpseg`, `send`, `drop`, `ipfrag`, `luaexec`, `pcap`, `udp2icmp`... Полный справочник — в исходнике `lua/zapret-antidpi.lua` и в manual.md.

Ключевые параметры: `blob=` (фейки tls/http/quic), `tcp_md5`, `tcp_seq=`, `repeats=`, `tls_mod=rnd,rndsni,dupsid`, `pos=1,midsld`, `seqovl=`, `ip_ttl/ip6_ttl`, `ip_autottl=delta,min-max`, `pattern=`, `tcp_ack=`, `tcp_ts_up`.

### Детектор неудач (autohostlist)

`zapret-auto.lua`: nfqws2 сам определяет домены, соединения с которыми срываются, и добавляет их в `ipset/zapret-hosts-auto.txt` (пишется от имени пользователя демона). Настраивается через `AUTOHOSTLIST_*`. Включается `MODE_FILTER=autohostlist`.

### Что это значит для ZapretGUI

- **Базовые стратегии** (Auto, YouTube, Gaming, Max Compatibility) = готовые блоки `NFQWS2_OPT` (+ MODE_FILTER). Хранить их как данные.
- **Custom-стратегии**: пользовательские `NFQWS2_OPT`-блоки с понятными названиями.
- **Автоподбор**: `blockcheck2.sh` умеет перебирать стратегии из `blockcheck2.d/` и находить рабочую — источник для Auto Configuration и Autopilot.

---

## 7. Хостлисты и IP-листы

Директория `ipset/`, фиксированные имена (gzip для генерируемых):

| Хостлист | Тип | IP-лист v4/v6 |
|---|---|---|
| `zapret-hosts-user.txt` | пользовательский, включающий | `zapret-ip-user.txt` / `zapret-ip-user6.txt` |
| `zapret-hosts-user-exclude.txt` | пользовательский, исключающий | `zapret-ip-exclude.txt` / `zapret-ip-exclude6.txt` |
| `zapret-hosts-user-ipban.txt` | пользовательский, заворот | `zapret-ip-user-ipban.txt`(+6) |
| `zapret-hosts.txt` | **генерируемый** (скачивается) | `zapret-ip.txt` / `zapret-ip6.txt` |
| — | генерируемые (заворот) | `zapret-ip-ipban.txt`(+6) |

Пользовательские листы ведутся вручную и не переписываются; генерируемые скачиваются скриптами `ipset/get_*.sh` (antifilter, реестр РКН, antizapret, re-filter и т.д.).

Цепочка обработки: `get_config.sh` (читает config, GETLIST, по умолч. `get_ipban.sh`) → скрипты `get_*.sh` → mdig (резолв в IP) → cut_local → sort -u → `create_ipset.sh` (загрузка в сеты, SAVERAM при малой памяти).

Обновление запущенного nfqws2: `SIGHUP` (hup_zapret_daemons) — перечитывает hostlist.

### Что это значит для ZapretGUI

- Вкладка «Защита»: редактирование `zapret-hosts-user.txt`, `zapret-hosts-user-exclude.txt`, кнопка обновления списков (запуск `get_config.sh` + reload).
- Статус: сколько доменов/IP в списках (файлы ipset/ читаются без root).
- `MODE_FILTER` рекомендуемый для десктопа: `hostlist` или `autohostlist` (на исследуемой системе — hostlist, 245 доменов пользовательского листа).

---

## 8. Диагностика и тестирование

- `blockcheck2.sh` — интерактивный перебор стратегий по сценариям из `blockcheck2.d/standard/*.sh` (`10-http-basic`, `20-multi`, `23-seqovl`, `24-syndata`, `25-fake`, `30-faked`, `35-hostfake`, `50-fake-multi`, `90-quic` и др.) и `blockcheck2.d/custom/` (списки HTTP/HTTPS TLS1.2/TLS1.3/QUIC сайтов). Требует root и сети.
- `nfqws2 --dry-run` — проверка параметров без запуска (нужен root из-за `--user`).
- `systemctl status`, `journalctl -u zapret2`, pidfile `/var/run/nfqws2_1.pid`.
- `zapret2 list-ifsets`, `list-table`.

### Что это значит для ZapretGUI

- Интегрировать blockcheck2 как headless-перебор стратегий (запуск под root через polkit, парсинг вывода).
- Веб-мониторинг (YouTube/Google/Discord...) — собственные проверки через Python (DNS/TCP/TLS/HTTP(S)/QUIC-пробы), не трогая blockcheck2 (он интерактивен).

---

## 9. Права и безопасность

- Всё управление (nft, iptables, sysctl, pidfiles в /var/run, запуск демона) — **только root**.
- nfqws2 стартует root и сбрасывает привилегии на `--user=zapret2` (uid 948 на Arch; создаётся sysusers.d).
- `nft list ruleset` от обычного юзера — Operation not permitted; статус firewall GUI читает либо через polkit-бэкенд, либо через скрипты (`list-ifsets` всё равно root).
- Пароль не хранить; pkexec — штатный механизм.
- При автохостлисте каталог ipset должен быть доступен на запись пользователю демона.

---

## 10. Совместимость (официальная)

- Статические бинарники работают на любом ядре с нужными модулями. Система запуска: **OpenWrt (гарантировано ≥18), классический Linux (systemd/openrc), Windows (winws2), FreeBSD/OpenBSD (только листы + ipfw/pf)**. MacOS не поддерживается.
- Требования на Linux: root, shell, cron/timer (для листов), netfilter с conntrack и NFQUEUE, curl, ipset или nft.

---

## 11. Фактическое состояние исследуемой машины (важно для тестирования)

1. Установлен `zapret2-bin 1.0.4-1` (AUR/Arch), `/opt/zapret2`, конфиг там же. Старый zapret (v72.13) тоже присутствует в `/opt/zapret` — **остались хвосты от старой установки**.
2. `zapret2.service` — enabled, active; демон работает под uid 948, pid-файл `/var/run/nfqws2_1.pid`.
3. Старый `zapret-list-update.timer` — enabled и указывает на старый `/opt/zapret/ipset/get_config.sh`. Родной `zapret2-list-update.timer` — disabled. **Обновление генерируемых списков сейчас фактически не работает корректно** (основных списков `zapret-hosts.txt`/`zapret-ip*.txt` нет — только пользовательские).
4. Задание: GUI должен уметь детектировать такое состояние и предлагать починку (выключить старый таймер, включить новый, запустить обновление листов).
5. `MODE_FILTER=hostlist` активен; autohostlist ранее включался (есть следы `zapret-hosts-auto.txt`).
6. В `/opt/zapret2` накопились бэкапы config — скрипты установки создают `config.backup-*`, `config.bak*`: критично, чтобы GUI тоже делал бэкапы при изменении стратегии.

---

## 12. Выводы для проектирования ZapretGUI

### Точки интеграции (checklist для бэкенда)

| Функция GUI | Как реализуется |
|---|---|
| Обнаружение zapret2 | Проверка `/opt/zapret2`, наличие `binaries/linux-x86_64/nfqws2` (архитектурно-зависимо), `--version` переданный в nfqws2 |
| ON/OFF | `systemctl start/stop zapret2.service` (root) |
| Статус | `systemctl is-active`, pidfile, `systemctl show -p ActiveState` |
| Применить стратегию | Сгенерировать новый `/opt/zapret2/config` (с бэкапом) → restart |
| Списки | Правка листов `zapret-hosts-user*.txt`, вызов `ipset/get_config.sh` (или выборочные `get_*.sh`), SIGHUP демонам |
| Auto Configuration | Чеки системы (systemd, nft, ядро) + вызов blockcheck2 headless + генерация стратегии |
| Autopilot | Мониторинг сервисов (собственный) + при деградации — перебор кандидатов blockcheck2 + смена стратегии |
| Диагностика | Собственные пробы (DNS/ICMP/TCP/TLS/HTTP/QUIC), статус службы, чтение листов, nft через root |
| Логи | `journalctl -u zapret2*`, файлы autohostlist-debug, логи собственного приложения |
| Установка zapret2 | По дистрибутиву: pacman (zapret2-bin), deb/rpm репозитории отсутствуют официально — сборка из исходников/бинарники с GitHub releases (задача Phase 11) |

### Архитектурные требования к GUI (из research)

1. **GUI не запускается от root.** Вся «тяжёлая» работа — через polkit-подтверждаемые бинарник/скрипт-помощник (helper), вызывающий systemctl и скрипты zapret2.
2. **Бэкенд должен уметь работать headless** (Phase 4 MVP Backend) — без UI, как CLI: `status`, `on`, `off`, `apply-strategy`, `check`, `diagnose`.
3. **Конфигурация GUI** (свои настройки: интервалы мониторинга, тема и т.д.) — отдельно от `/opt/zapret2/config`. Формат — см. Phase 3 (Data Model), кандидат: YAML/JSON.
4. **Стратегии** — данные: `{name, description, mods: [nfqws2-аргументы], mode_filter, ports, pkt_out/in}`. Формат версионируемый (план §10).
5. **Мониторинг**: собственные PHP-free пробы; интервал 5 мин; только когда zapret ON.
6. **Автопилот** — отдельный модуль поверх мониторинга + перебор стратегий; полностью отключаемый.
7. **Проверять хвосты старых установок zapret1/старых таймеров** и предлагать очистку.
8. **Перед любым изменением config — бэкап** в `/opt/zapret2/` (по образцу самих скриптов zapret2).

### Протестированная совместимость (пока)

| Дистрибутив | Status |
|---|---|
| Arch Linux (zapret2-bin 1.0.4) | ✔ Проверено вживую (эта машина) |
| Debian/Ubuntu/Fedora/openSUSE | Не проверено (из плана Phase 12; бэкенд — поверх systemctl + sysv-скрипта zapret2, ожидается совместимость, необходимо тестировать) |

---

## 13. Риски и открытые вопросы

1. **Смена путей в zapret2**: конфиг в /opt, версия бинарников в `binaries/linux-<arch>/` — детект должен быть гибким (`find` по известным путям + `which`).
2. **blockcheck2 headless**: интерактивный по своей природе; нужен research его CLI-флагов (есть ли non-interactive режим) перед реализацией Auto Configuration/Autopilot.
3. **QUIC-профиль**: UDP-перехват 443 может создавать нагрузку; в стратегиях для слабых машин учесть.
4. **MODE_FILTER=none** в бэкапе конфига — GUI должен предупреждать о последствиях (десинк всего трафика 80/443).
5. **Проверка списков**: GUI не должен слепо запускать `get_config.sh` без понимания GETLIST-настроек. План: на первых порах — только пользовательские листы + ручной запуск обновления генерируемых.
6. **CLI nfqws2 для dry-run валидации стратегий** — использовать при сохранении custom-стратегий.
7. **Аппаратный минимум** (VPS/десктоп/слабый ноутбук): не гонять autohostlist+перебор одновременно на слабых машинах без подтверждения пользователя.