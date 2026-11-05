#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_ROOT=${ZLS_HOME:-"$HOME/.zapret-linux-server"}
SERVER_REPOSITORY=${ZLS_REPOSITORY:-"https://github.com/Heisenberg4441/zapret-linux-server.git"}
ZAPRET_REPOSITORY=${ZAPRET_REPOSITORY:-"https://github.com/bol-van/zapret.git"}
FLOWSEAL_REPOSITORY=${FLOWSEAL_REPOSITORY:-"https://github.com/Flowseal/zapret-discord-youtube.git"}

fail() {
    printf 'Ошибка: %s\n' "$*" >&2
    exit 1
}

command -v git >/dev/null 2>&1 || fail "Установите git и повторите запуск."
command -v docker >/dev/null 2>&1 || fail "Установите Docker и Docker Compose."
[[ "$(uname -s)" == "Linux" ]] || fail "Установщик предназначен для Linux."
docker info >/dev/null 2>&1 || fail "Docker daemon недоступен или у пользователя нет прав."
docker compose version >/dev/null 2>&1 || fail "Плагин Docker Compose не найден."

fetch_repo() {
    local name=$1 repository=$2 branch=$3
    local destination="$INSTALL_ROOT/$name"
    if [[ -d "$destination/.git" ]]; then
        printf 'Обновление %s...\n' "$name"
        git -C "$destination" pull --ff-only
    elif [[ -e "$destination" ]]; then
        fail "Каталог $destination существует, но не является Git-репозиторием. Переместите его."
    else
        printf 'Загрузка %s...\n' "$name"
        git clone --depth 1 --branch "$branch" "$repository" "$destination"
    fi
}

mkdir -p "$INSTALL_ROOT"
fetch_repo zapret-linux-server "$SERVER_REPOSITORY" master
fetch_repo zapret "$ZAPRET_REPOSITORY" master
fetch_repo zapret-discord-youtube "$FLOWSEAL_REPOSITORY" main

APP="$INSTALL_ROOT/zapret-linux-server"
[[ -x "$APP/zls" ]] || fail "В загруженном репозитории не найден $APP/zls."

printf '\nФайлы установлены в %s\n' "$INSTALL_ROOT"
if [[ "${ZLS_SKIP_START:-0}" == "1" ]]; then
    printf 'Автозапуск пропущен. Запуск: %s/zls setup\n' "$APP"
    exit 0
fi

args=()
if [[ -n "${ZLS_STRATEGY:-}" ]]; then
    args+=("$ZLS_STRATEGY")
fi
if [[ "${ZLS_YOUTUBE_FIX:-0}" == "1" ]]; then
    args+=(--youtube-fix)
fi

if [[ -t 0 ]]; then
    "$APP/zls" setup "${args[@]}"
elif [[ -r /dev/tty ]]; then
    "$APP/zls" setup "${args[@]}" </dev/tty
else
    if [[ ${#args[@]} -eq 0 ]]; then
        args=("general.bat")
    fi
    "$APP/zls" setup "${args[@]}" </dev/null
fi

printf '\nПрокси запущен на порту %s.\n' "${PROXY_PORT:-3128}"
printf 'Управление: %s/zls status | logs -f | test | down\n' "$APP"
