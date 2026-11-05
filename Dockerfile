FROM debian:bookworm-slim AS build

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        libmnl-dev \
        libnetfilter-queue-dev \
        zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /src
COPY zapret/nfq /src/nfq
RUN make -C /src/nfq

FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        ca-certificates \
        curl \
        iptables \
        libmnl0 \
        libnetfilter-queue1 \
        procps \
        python3 \
        squid \
        zlib1g \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --system --gid 13123 zapret \
    && useradd --system --uid 13123 --gid 13123 --no-create-home --shell /usr/sbin/nologin zapret

COPY --from=build /src/nfq/nfqws /opt/zapret/nfqws
COPY zapret-discord-youtube/general*.bat /opt/zapret-discord-youtube/
COPY zapret-discord-youtube/lists /opt/zapret-discord-youtube/lists
COPY zapret-discord-youtube/bin /opt/zapret-discord-youtube/bin
RUN find /opt/zapret-discord-youtube/bin -type f ! -name '*.bin' -delete

COPY zapret-linux-server/bin/zlsctl.py /opt/zls/zlsctl.py
COPY zapret-linux-server/bin/entrypoint.sh /opt/zls/entrypoint.sh
COPY zapret-linux-server/bin/healthcheck.sh /opt/zls/healthcheck.sh
COPY zapret-linux-server/bin/test-proxy.sh /opt/zls/test-proxy.sh
RUN chmod 0755 /opt/zapret/nfqws /opt/zls/*.sh /opt/zls/zlsctl.py

ENTRYPOINT ["/opt/zls/entrypoint.sh"]
