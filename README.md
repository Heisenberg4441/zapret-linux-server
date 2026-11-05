# zapret-linux-server

HTTP-прокси для домашней сети, исходящий трафик которого обрабатывается `nfqws` из `zapret`. Стратегии, списки доменов и fake-пакеты берутся из соседнего каталога `zapret-discord-youtube`.

Предназначено прежде всего для PlayStation и других устройств, где можно вручную указать HTTP-прокси. Всё запускается в Docker, на хост ставятся только Docker и Docker Compose.

## Как это работает

```text
Консоль → HTTP CONNECT → Squid → nfqws → интернет
```

Squid принимает обычные HTTP-запросы и HTTPS через `CONNECT`, без расшифровки TLS. `nfqws` перехватывает только исходящие пакеты процессов с UID `13123` и применяет выбранную стратегию. Для этого контейнер использует `network_mode: host` и capabilities `NET_ADMIN`, `NET_RAW`.

Создаётся отдельная цепочка iptables `ZLS_NFQWS`; при штатной остановке она удаляется. Правила не перехватывают весь трафик хоста, но контейнер всё равно имеет право изменять firewall в сетевом namespace хоста — запускайте его только на доверенном сервере.

## Требования

- Linux на хомлабе; протестированные архитектуры зависят от поддержки базового Debian-образа.
- Docker с плагином Compose v2.
- Каталоги `zapret`, `zapret-discord-youtube` и `zapret-linux-server` должны оставаться рядом.
- Свободный TCP-порт `3128` на хосте.
- Модули ядра для `NFQUEUE`, `iptables`, `owner`, `connbytes` и `multiport` (в обычных серверных дистрибутивах они уже есть).

**Нужен Docker именно на Linux.** Docker Desktop на macOS/Windows запускает контейнер внутри виртуальной машины, поэтому консоль не сможет использовать этот вариант как обычный LAN-прокси.

## Быстрый старт

Одна команда на Linux-хосте с Git, Docker и Docker Compose:

```bash
curl -fsSL https://raw.githubusercontent.com/Heisenberg4441/zapret-linux-server/master/install.sh | bash
```

Установщик скачает этот репозиторий, `zapret` и `zapret-discord-youtube` в `~/.zapret-linux-server`, соберёт образ, предложит стратегию и запустит прокси. При `curl | bash` выбор стратегии выполняется через `/dev/tty`, поэтому терминал остаётся интерактивным. Повторный запуск обновляет репозитории через `git pull --ff-only` и не удаляет выбранную конфигурацию.

Для неинтерактивной установки:

```bash
curl -fsSL https://raw.githubusercontent.com/Heisenberg4441/zapret-linux-server/master/install.sh | \
  ZLS_STRATEGY='general (ALT11).bat' ZLS_YOUTUBE_FIX=1 bash
```

Другой каталог установки задаётся переменной `ZLS_HOME`. Только скачать файлы без запуска можно с `ZLS_SKIP_START=1`.

Если исходники уже находятся рядом, можно запустить вручную:

```bash
cd zapret-linux-server
./zls setup
```

Запущенный прокси слушает `0.0.0.0:3128`, но Squid разрешает подключения только из loopback и приватных IPv4-сетей.

Узнать адрес сервера:

```bash
hostname -I
```

Проверить выбранный конфиг и реальные HTTPS-подключения через прокси:

```bash
./zls status
./zls test
```

`test` проверяет не только главную страницу YouTube, но и TLS к `redirector.googlevideo.com`, а также Discord и его gateway. Успешный ответ не гарантирует работу каждого видео: клиент выбирает конкретные CDN-серверы самостоятельно.

## Настройка консоли

### PlayStation 5

Откройте **Настройки → Сеть → Настройки → Настроить подключение к Интернету**, выберите соединение и ручную настройку. В пункте **Прокси-сервер** укажите:

- адрес: LAN IP сервера с Docker;
- порт: `3128`.

На PS4 прокси также задаётся в ручных настройках сетевого подключения. [Официальная инструкция PlayStation](https://www.playstation.com/en-us/support/connectivity/internet-connect-playstation/).

### Xbox

В системных настройках Xbox нет обычной настройки HTTP-прокси: в Advanced settings доступны IP и DNS, но не прокси. Поэтому **этот контейнер нельзя подключить к Xbox аналогично PS5**. Для Xbox нужен другой сетевой слой — прозрачный шлюз, VPN или раздача соединения через компьютер. Данная утилита не настраивает их. [Официальное описание сетевых настроек Xbox](https://support.xbox.com/en-US/help/hardware-network/connect-network/xbox-one-network-connection-errors).

### UDP и Discord Voice

HTTP-прокси переносит TCP. QUIC и Discord Voice UDP с консоли через такую системную настройку не проходят: эти соединения устройство либо переключает на TCP, либо отправляет напрямую. Профили UDP из BAT-файлов сохраняются в `nfqws`, но сами по себе не превращают HTTP-прокси в UDP-шлюз. Для гарантированного голосового Discord нужен VPN/прозрачный маршрутизатор.

## Выбор стратегии

```bash
./zls list
./zls select                         # интерактивный выбор
./zls select 'general (ALT11).bat'  # по имени
./zls select 11                     # по номеру из list
./zls restart
```

Game Filter намеренно отключён, как в исходных конфигах по умолчанию. Порт-заглушка `12` не добавляется в firewall.

Не существует стратегии, рабочей у всех провайдеров. Если один сервис работает, а другой нет, перебирайте `ALT`, `FAKE TLS AUTO`, `SIMPLE FAKE` и `EXP` по одному и повторяйте `./zls test`.

### Если YouTube открывается, но видео не играет

В issues часто встречается таймаут TLS именно к `*.googlevideo.com` ([#15989](https://github.com/Flowseal/zapret-discord-youtube/issues/15989)). В [#17781](https://github.com/Flowseal/zapret-discord-youtube/issues/17781) части пользователей помог отдельный профиль `hostfakesplit` для `googlevideo.com`.

Он добавлен как опция и ставится **перед** общим профилем `list-google.txt`:

```bash
./zls select --youtube-fix
./zls restart
./zls test
```

Вернуть исходную стратегию без дополнительного профиля:

```bash
./zls select --no-youtube-fix
./zls restart
```

Для `ALT13`, `EXP` и других конфигов, где Google уже обрабатывается через `hostfakesplit`, дублирующий профиль не добавляется. Это точечный workaround, а не универсальное исправление.

Также учитывайте рекомендации из [обсуждения YouTube #251](https://github.com/Flowseal/zapret-discord-youtube/discussions/251): проверить другой браузер, отключить блокировщики рекламы и попробовать разные настройки QUIC/Kyber. Squid выполняет DNS-резолвинг на сервере, поэтому DNS Docker-хоста должен выдавать реальные адреса. `zapret` не обходит блокировку по IP.

## Команды

```text
./zls setup                 сборка, выбор конфига, запуск
./zls build                 пересборка после обновления zapret/конфигов
./zls start | up            запуск
./zls stop | down           остановка и очистка firewall
./zls restart               перечитать выбранную стратегию
./zls status                контейнер и активный конфиг
./zls logs -f               логи nfqws и Squid
./zls show                  полные аргументы nfqws
./zls validate              nfqws --dry-run для выбранного конфига
./zls validate --all        проверка всех BAT-файлов
./zls test                  сквозная проверка через HTTP-прокси
```

## Настройки и свои списки

В `settings.env`:

- `PROXY_BIND_ADDR`, `PROXY_PORT` — адрес и порт Squid;
- `LAN_CIDRS` — разрешённые сети через пробел;
- `DISABLE_IPV6=1` — по умолчанию обрабатывается только IPv4;
- `NFQWS_QNUM`, `NFQWS_MARK`, `NFQWS_PKT_OUT` — параметры перехвата;
- `ZLS_UID` — UID, ограничивающий перехват; не меняйте без изменения пользователя в образе.

После изменения `settings.env` контейнер нужно пересоздать:

```bash
./zls down
./zls up
```

Пользовательские списки находятся в `./lists` и подключаются в контейнер read-only:

- `list-general-user.txt` — дополнительные домены;
- `list-exclude-user.txt` — исключения доменов;
- `ipset-exclude-user.txt` — исключения IP/CIDR.

После их изменения выполните `./zls restart`.

Не оставляйте прокси открытым в интернет. Дополнительно ограничьте порт `3128` на хостовом firewall своей LAN-подсетью.

## Обновление исходников и удаление

После обновления содержимого соседних `zapret` или `zapret-discord-youtube`:

```bash
./zls build
./zls down
./zls up
```

Остановка и удаление контейнера:

```bash
./zls down
```

Файл `config/selection.json` сохраняет только выбор стратегии. Исходные каталоги `zapret` и `zapret-discord-youtube` утилита не изменяет.
