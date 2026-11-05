#!/usr/bin/env python3
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys

FLOWSEAL = Path(os.environ.get("FLOWSEAL_DIR", "/opt/zapret-discord-youtube"))
CONFIG_DIR = Path(os.environ.get("ZLS_CONFIG_DIR", "/config"))
SELECTION_FILE = CONFIG_DIR / "selection.json"
NFQWS = os.environ.get("NFQWS_BIN", "/opt/zapret/nfqws")
USER_LISTS = {
    "list-general-user.txt",
    "list-exclude-user.txt",
    "ipset-exclude-user.txt",
}
YOUTUBE_FIX = shlex.split(
    "--filter-tcp=443 --hostlist-domains=googlevideo.com --ip-id=zero "
    "--dpi-desync=hostfakesplit --dpi-desync-repeats=5 "
    "--dpi-desync-fooling=ts "
    "--dpi-desync-hostfakesplit-mod=host=www.google.com --new"
)


class StrategyError(ValueError):
    pass


def strategies():
    return sorted(
        FLOWSEAL.glob("general*.bat"),
        key=lambda path: (path.name != "general.bat", natural_key(path.name)),
    )


def natural_key(value):
    return [int(part) if part.isdigit() else part.lower() for part in re.split(r"(\d+)", value)]


def load_selection(required=True):
    if not SELECTION_FILE.exists():
        if required:
            raise StrategyError("Стратегия не выбрана. Выполните: ./zls select")
        return None
    try:
        selection = json.loads(SELECTION_FILE.read_text(encoding="utf-8"))
        strategy_path(selection["strategy"])
        selection["youtube_hostfakesplit"] = bool(selection.get("youtube_hostfakesplit"))
        return selection
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise StrategyError(f"Повреждён {SELECTION_FILE}: {exc}") from exc


def save_selection(selection):
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    temporary = SELECTION_FILE.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    temporary.replace(SELECTION_FILE)


def strategy_path(name):
    candidate = Path(name)
    if candidate.name != name or not name.endswith(".bat"):
        raise StrategyError("Укажите имя BAT-файла из списка ./zls list")
    path = FLOWSEAL / name
    if not path.is_file() or path.parent != FLOWSEAL:
        raise StrategyError(f"Стратегия не найдена: {name}")
    return path


def resolve_strategy(value):
    if value and value.isdigit():
        items = strategies()
        index = int(value)
        if not 1 <= index <= len(items):
            raise StrategyError(f"Номер должен быть от 1 до {len(items)}")
        return items[index].name
    if value:
        return strategy_path(value).name
    return None


def extract_command(path):
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    collecting = False
    parts = []
    for line in lines:
        stripped = line.strip()
        if not collecting and "winws.exe" in stripped and "--wf-" in stripped:
            collecting = True
        if not collecting:
            continue
        continued = stripped.endswith("^")
        parts.append(stripped[:-1] if continued else stripped)
        if not continued:
            break
    if not parts:
        raise StrategyError(f"В {path.name} не найдена команда winws.exe")
    return " ".join(parts)


def parse_strategy(name, youtube_fix=False):
    path = strategy_path(name)
    command = extract_command(path)
    replacements = {
        "%BIN%": str(FLOWSEAL / "bin") + "/",
        "%LISTS%": str(FLOWSEAL / "lists") + "/",
        "%GameFilterTCP%": "12",
        "%GameFilterUDP%": "12",
    }
    for source, target in replacements.items():
        command = command.replace(source, target)
    tokens = shlex.split(command, posix=True)
    tokens = [token.replace("=^!", "=!") for token in tokens]

    try:
        executable = next(index for index, token in enumerate(tokens) if token.endswith("winws.exe"))
    except StopIteration as exc:
        raise StrategyError(f"Не найден исполняемый файл в {name}") from exc
    tokens = tokens[executable + 1 :]

    tcp_ports = ""
    udp_ports = ""
    profiles = []
    for token in tokens:
        if token.startswith("--wf-tcp="):
            tcp_ports = token.split("=", 1)[1]
        elif token.startswith("--wf-udp="):
            udp_ports = token.split("=", 1)[1]
        elif not token.startswith("--wf-"):
            profiles.append(token)
    if not profiles:
        raise StrategyError(f"В {name} нет профилей десинхронизации")

    profiles = [map_user_list(token) for token in profiles]
    validate_files(name, profiles)
    if youtube_fix and not has_googlevideo_specialization(profiles):
        profiles = YOUTUBE_FIX + profiles

    args = base_args() + profiles
    ports = {
        "tcp": normalize_ports(tcp_ports),
        "udp": normalize_ports(udp_ports),
    }
    return args, ports


def map_user_list(token):
    prefix = str(FLOWSEAL / "lists") + "/"
    for option in ("--hostlist=", "--hostlist-exclude=", "--ipset=", "--ipset-exclude="):
        if token.startswith(option):
            value = token[len(option) :]
            if value.startswith(prefix) and Path(value).name in USER_LISTS:
                return option + str(CONFIG_DIR / "lists" / Path(value).name)
    return token


def validate_files(name, tokens):
    path_options = (
        "--hostlist=",
        "--hostlist-exclude=",
        "--ipset=",
        "--ipset-exclude=",
        "--dpi-desync-split-seqovl-pattern=",
        "--dpi-desync-fakedsplit-pattern=",
        "--dpi-desync-fake-http=",
        "--dpi-desync-fake-tls=",
        "--dpi-desync-fake-quic=",
        "--dpi-desync-fake-discord=",
        "--dpi-desync-fake-stun=",
        "--dpi-desync-fake-unknown=",
        "--dpi-desync-fake-unknown-udp=",
    )
    for token in tokens:
        for option in path_options:
            if not token.startswith(option):
                continue
            value = token[len(option) :]
            if not value or value.startswith(("0x", "!")):
                continue
            if "@" in value:
                value = value.rsplit("@", 1)[1]
            if value.startswith("/") and not Path(value).is_file():
                raise StrategyError(f"{name}: файл не найден: {value}")


def has_googlevideo_specialization(tokens):
    profiles = []
    current = []
    for token in tokens:
        if token == "--new":
            profiles.append(current)
            current = []
        else:
            current.append(token)
    profiles.append(current)
    for profile in profiles:
        domains = [token for token in profile if token.startswith("--hostlist-domains=")]
        google_list = any(token.endswith("/list-google.txt") for token in profile)
        hostfakesplit = any("hostfakesplit" in token for token in profile if token.startswith("--dpi-desync="))
        if any("googlevideo.com" in token for token in domains) or (google_list and hostfakesplit):
            return True
    return False


def normalize_ports(value):
    ports = [item for item in value.split(",") if item and item != "12"]
    result = ",".join(ports)
    if result and not re.fullmatch(r"\d+(?:-\d+)?(?:,\d+(?:-\d+)?)*", result):
        raise StrategyError(f"Некорректный список портов: {result}")
    for item in ports:
        bounds = [int(bound) for bound in item.split("-")]
        if any(bound < 1 or bound > 65535 for bound in bounds) or (
            len(bounds) == 2 and bounds[0] > bounds[1]
        ):
            raise StrategyError(f"Некорректный диапазон портов: {item}")
    return result


def base_args():
    qnum = integer_env("NFQWS_QNUM", 200, 0, 65535)
    mark = os.environ.get("NFQWS_MARK", "0x40000000")
    try:
        int(mark, 0)
    except ValueError as exc:
        raise StrategyError(f"Некорректный NFQWS_MARK: {mark}") from exc
    return [
        f"--qnum={qnum}",
        "--user=zapret",
        f"--dpi-desync-fwmark={mark}",
        "--debug=1",
    ]


def integer_env(name, default, minimum, maximum):
    raw = os.environ.get(name, str(default))
    try:
        value = int(raw)
    except ValueError as exc:
        raise StrategyError(f"{name} должен быть числом") from exc
    if not minimum <= value <= maximum:
        raise StrategyError(f"{name} должен быть от {minimum} до {maximum}")
    return value


def boolean_env(name, default):
    raw = os.environ.get(name, default).lower()
    if raw not in {"0", "1"}:
        raise StrategyError(f"{name} должен быть 0 или 1")
    return raw == "1"


def render_squid(output_dir):
    bind = os.environ.get("PROXY_BIND_ADDR", "0.0.0.0")
    try:
        ipaddress.ip_address(bind)
    except ValueError as exc:
        raise StrategyError(f"Некорректный PROXY_BIND_ADDR: {bind}") from exc
    listen = f"[{bind}]" if ":" in bind else bind
    port = integer_env("PROXY_PORT", 3128, 1, 65535)
    networks = []
    for raw in os.environ.get(
        "LAN_CIDRS", "127.0.0.0/8 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16"
    ).split():
        try:
            networks.append(str(ipaddress.ip_network(raw, strict=False)))
        except ValueError as exc:
            raise StrategyError(f"Некорректная сеть в LAN_CIDRS: {raw}") from exc
    if not networks:
        raise StrategyError("LAN_CIDRS не должен быть пустым")

    acls = "\n".join(f"acl localnet src {network}" for network in networks)
    config = f"""visible_hostname zapret-linux-server
http_port {listen}:{port}
acl SSL_ports port 443 1024-65535
acl Safe_ports port 80 443 1024-65535
acl CONNECT method CONNECT
{acls}
http_access deny !Safe_ports
http_access deny CONNECT !SSL_ports
http_access allow manager localhost
http_access deny manager
http_access allow localhost
http_access allow localnet
http_access deny all
cache deny all
cache_mem 32 MB
access_log stdio:{output_dir}/squid-access.log
cache_log {output_dir}/squid-cache.log
cache_store_log none
pid_filename {output_dir}/squid.pid
cache_effective_user zapret
cache_effective_group zapret
forwarded_for delete
httpd_suppress_version_string on
shutdown_lifetime 3 seconds
"""
    (output_dir / "squid.conf").write_text(config, encoding="utf-8")


def render(selection, output_dir):
    args, ports = parse_strategy(selection["strategy"], selection["youtube_hostfakesplit"])
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "nfqws.args").write_text("\n".join(args) + "\n", encoding="utf-8")
    packet_limit = integer_env("NFQWS_PKT_OUT", 12, 1, 100)
    uid = integer_env("ZLS_UID", 13123, 1, 65534)
    values = {
        "NFQWS_PORTS_TCP": ports["tcp"],
        "NFQWS_PORTS_UDP": ports["udp"],
        "NFQWS_PKT_OUT": str(packet_limit),
        "NFQWS_QNUM": str(integer_env("NFQWS_QNUM", 200, 0, 65535)),
        "NFQWS_MARK": os.environ.get("NFQWS_MARK", "0x40000000"),
        "ZLS_UID": str(uid),
        "DISABLE_IPV6": "1" if boolean_env("DISABLE_IPV6", "1") else "0",
    }
    (output_dir / "firewall.env").write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in values.items()),
        encoding="utf-8",
    )
    render_squid(output_dir)
    return args, ports


def print_selection(selection, with_args=False):
    fix = "включён" if selection["youtube_hostfakesplit"] else "выключен"
    print(f"Стратегия: {selection['strategy']}")
    print(f"YouTube hostfakesplit: {fix}")
    if with_args:
        args, ports = parse_strategy(selection["strategy"], selection["youtube_hostfakesplit"])
        print(f"TCP capture: {ports['tcp'] or '-'}; UDP capture: {ports['udp'] or '-'}")
        print(shlex.join(args))


def command_list(_args):
    for index, path in enumerate(strategies(), 1):
        print(f"{index:2d}. {path.name}")


def command_select(args):
    current = load_selection(required=False) or {
        "strategy": "general.bat",
        "youtube_hostfakesplit": False,
    }
    name = resolve_strategy(args.strategy)
    if not name and (args.youtube_fix or args.no_youtube_fix) and SELECTION_FILE.exists():
        name = current["strategy"]
    if not name:
        if not sys.stdin.isatty():
            raise StrategyError("В неинтерактивном режиме укажите имя или номер стратегии")
        command_list(args)
        default = current["strategy"]
        raw = input(f"\nНомер или имя стратегии [{default}]: ").strip()
        name = resolve_strategy(raw) if raw else default
    youtube_fix = current["youtube_hostfakesplit"]
    if args.youtube_fix:
        youtube_fix = True
    if args.no_youtube_fix:
        youtube_fix = False
    selection = {"strategy": name, "youtube_hostfakesplit": youtube_fix}
    save_selection(selection)
    print_selection(selection)


def command_show(_args):
    print_selection(load_selection(), with_args=True)


def command_validate(args):
    selections = (
        [{"strategy": path.name, "youtube_hostfakesplit": False} for path in strategies()]
        if args.all
        else [load_selection()]
    )
    failures = 0
    for selection in selections:
        try:
            parsed, _ports = parse_strategy(selection["strategy"], selection["youtube_hostfakesplit"])
            result = subprocess.run(
                [NFQWS] + parsed + ["--dry-run"],
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            if result.returncode:
                failures += 1
                print(f"[FAIL] {selection['strategy']}")
                print((result.stderr or result.stdout).strip())
            else:
                print(f"[OK]   {selection['strategy']}")
        except (StrategyError, subprocess.TimeoutExpired) as exc:
            failures += 1
            print(f"[FAIL] {selection['strategy']}: {exc}")
    if failures:
        raise StrategyError(f"Проверок не прошло: {failures}")


def command_render(args):
    parsed, ports = render(load_selection(), Path(args.output_dir))
    print_selection(load_selection())
    print(f"TCP capture: {ports['tcp'] or '-'}; UDP capture: {ports['udp'] or '-'}")
    print(f"Профилей nfqws: {parsed.count('--new') + 1}")


def parser():
    result = argparse.ArgumentParser(description="zapret-linux-server control")
    commands = result.add_subparsers(dest="command", required=True)
    commands.add_parser("list")
    select = commands.add_parser("select")
    select.add_argument("strategy", nargs="?")
    select.add_argument("--youtube-fix", action="store_true")
    select.add_argument("--no-youtube-fix", action="store_true")
    commands.add_parser("show")
    validate = commands.add_parser("validate")
    validate.add_argument("--all", action="store_true")
    render_parser = commands.add_parser("render")
    render_parser.add_argument("--output-dir", default="/run/zls")
    return result


def main():
    args = parser().parse_args()
    handlers = {
        "list": command_list,
        "select": command_select,
        "show": command_show,
        "validate": command_validate,
        "render": command_render,
    }
    try:
        handlers[args.command](args)
    except StrategyError as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
