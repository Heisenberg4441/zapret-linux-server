#!/usr/bin/env bash
set -Eeuo pipefail

pgrep -x nfqws >/dev/null
pgrep -x squid >/dev/null
addr=${PROXY_BIND_ADDR:-0.0.0.0}
if [[ "$addr" == "0.0.0.0" || "$addr" == "::" ]]; then
    addr=127.0.0.1
elif [[ "$addr" == *:* ]]; then
    addr="[$addr]"
fi
curl --silent --show-error --fail --max-time 5 \
    "http://$addr:${PROXY_PORT:-3128}/squid-internal-mgr/info" >/dev/null
