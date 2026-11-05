#!/usr/bin/env bash
set -Eeuo pipefail

if [[ $# -gt 0 ]]; then
    exec "$@"
fi

RUNTIME=/run/zls
CHAIN=ZLS_NFQWS
NFQWS_PID=
SQUID_PID=
IPV4_READY=0
IPV6_READY=0

mkdir -p "$RUNTIME"
python3 /opt/zls/zlsctl.py render --output-dir "$RUNTIME"
# shellcheck disable=SC1091
source "$RUNTIME/firewall.env"

cleanup() {
    local exit_code=$?
    trap - EXIT INT TERM
    if [[ -n "$SQUID_PID" ]]; then
        kill "$SQUID_PID" 2>/dev/null || true
    fi
    if [[ -n "$NFQWS_PID" ]]; then
        kill "$NFQWS_PID" 2>/dev/null || true
    fi
    if [[ "$IPV4_READY" == 1 ]]; then
        iptables --wait 5 -t mangle -D OUTPUT -j "$CHAIN" 2>/dev/null || true
        iptables --wait 5 -t mangle -F "$CHAIN" 2>/dev/null || true
        iptables --wait 5 -t mangle -X "$CHAIN" 2>/dev/null || true
    fi
    if [[ "$IPV6_READY" == 1 ]]; then
        ip6tables --wait 5 -t mangle -D OUTPUT -j "$CHAIN" 2>/dev/null || true
        ip6tables --wait 5 -t mangle -F "$CHAIN" 2>/dev/null || true
        ip6tables --wait 5 -t mangle -X "$CHAIN" 2>/dev/null || true
    fi
    wait 2>/dev/null || true
    exit "$exit_code"
}
trap cleanup EXIT INT TERM

mapfile -t NFQWS_ARGS < "$RUNTIME/nfqws.args"
/opt/zapret/nfqws "${NFQWS_ARGS[@]}" --dry-run
squid -k parse -f "$RUNTIME/squid.conf"

queue_rules() {
    local tool=$1
    "$tool" --wait 5 -t mangle -N "$CHAIN" 2>/dev/null || true
    "$tool" --wait 5 -t mangle -F "$CHAIN"
    "$tool" --wait 5 -t mangle -A "$CHAIN" -m owner ! --uid-owner "$ZLS_UID" -j RETURN
    "$tool" --wait 5 -t mangle -A "$CHAIN" -m mark --mark "$NFQWS_MARK/$NFQWS_MARK" -j RETURN
    if [[ -n "$NFQWS_PORTS_TCP" ]]; then
        "$tool" --wait 5 -t mangle -A "$CHAIN" -p tcp -m multiport --dports "$NFQWS_PORTS_TCP" \
            -m connbytes --connbytes-dir=original --connbytes-mode=packets \
            --connbytes "1:$NFQWS_PKT_OUT" -j NFQUEUE --queue-num "$NFQWS_QNUM" --queue-bypass
    fi
    if [[ -n "$NFQWS_PORTS_UDP" ]]; then
        "$tool" --wait 5 -t mangle -A "$CHAIN" -p udp -m multiport --dports "$NFQWS_PORTS_UDP" \
            -m connbytes --connbytes-dir=original --connbytes-mode=packets \
            --connbytes "1:$NFQWS_PKT_OUT" -j NFQUEUE --queue-num "$NFQWS_QNUM" --queue-bypass
    fi
    if ! "$tool" --wait 5 -t mangle -C OUTPUT -j "$CHAIN" 2>/dev/null; then
        "$tool" --wait 5 -t mangle -I OUTPUT 1 -j "$CHAIN"
    fi
}

IPV4_READY=1
queue_rules iptables
if [[ "$DISABLE_IPV6" == 0 ]]; then
    IPV6_READY=1
    queue_rules ip6tables
fi

printf 'Запуск nfqws (UID %s, queue %s)\n' "$ZLS_UID" "$NFQWS_QNUM"
/opt/zapret/nfqws "${NFQWS_ARGS[@]}" &
NFQWS_PID=$!
printf 'Запуск HTTP-прокси на %s:%s\n' "${PROXY_BIND_ADDR:-0.0.0.0}" "${PROXY_PORT:-3128}"
squid -N -d1 -f "$RUNTIME/squid.conf" &
SQUID_PID=$!

sleep 2
kill -0 "$NFQWS_PID"
kill -0 "$SQUID_PID"

status=0
wait -n "$NFQWS_PID" "$SQUID_PID" || status=$?
printf 'Один из процессов завершился (код %s), останавливаю контейнер.\n' "$status" >&2
exit "${status:-1}"
