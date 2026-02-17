FROM alpine:3.19

# Vegeta version to install
ARG VEGETA_VERSION=12.12.0

# Install vegeta binary from GitHub releases
RUN apk add --no-cache wget ca-certificates && \
    wget -q -O /tmp/vegeta.tar.gz \
        "https://github.com/tsenart/vegeta/releases/download/v${VEGETA_VERSION}/vegeta_${VEGETA_VERSION}_linux_amd64.tar.gz" && \
    tar -xzf /tmp/vegeta.tar.gz -C /usr/local/bin vegeta && \
    chmod +x /usr/local/bin/vegeta && \
    rm /tmp/vegeta.tar.gz && \
    apk del wget

COPY run.sh /usr/local/bin/run.sh
RUN chmod +x /usr/local/bin/run.sh

# Default results mount point
VOLUME ["/results"]

ENTRYPOINT ["/usr/local/bin/run.sh"]
