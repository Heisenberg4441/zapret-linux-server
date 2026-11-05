#!/usr/bin/env bash
set -uo pipefail

addr=${PROXY_BIND_ADDR:-0.0.0.0}
if [[ "$addr" == "0.0.0.0" || "$addr" == "::" ]]; then
    addr=127.0.0.1
elif [[ "$addr" == *:* ]]; then
    addr="[$addr]"
fi
proxy="http://$addr:${PROXY_PORT:-3128}"
failed=0

check() {
    local name=$1 url=$2 code
    code=$(curl --silent --show-error --output /dev/null \
        --proxy "$proxy" --connect-timeout 7 --max-time 20 \
        --write-out '%{http_code}' "$url") || code=000
    if [[ "$code" == "000" ]]; then
        printf '[FAIL] %-24s %s\n' "$name" "$url"
        failed=1
    else
        printf '[OK]   %-24s HTTP %s\n' "$name" "$code"
    fi
}

check 'YouTube' 'https://www.youtube.com/generate_204'
check 'YouTube video host' 'https://redirector.googlevideo.com/generate_204'
check 'Discord' 'https://discord.com/'
check 'Discord gateway' 'https://gateway.discord.gg/'

if ((failed)); then
    printf '\nПроверка не пройдена. Попробуйте другую стратегию: ./zls select\n' >&2
    printf 'Если не работает только видео: ./zls select --youtube-fix\n' >&2
else
    printf '\nTLS и HTTP-доступность проверенных адресов: OK.\n'
    printf 'Это не гарантирует воспроизведение всех роликов: конкретный CDN выбирает клиент.\n'
fi
exit "$failed"
