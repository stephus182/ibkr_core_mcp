FROM eclipse-temurin:21

WORKDIR /app

RUN apt-get update && apt-get install -y unzip curl && rm -rf /var/lib/apt/lists/*

# Download and unzip the official IBKR Client Portal Gateway
RUN mkdir api_gateway && cd api_gateway && \
    curl -O https://download2.interactivebrokers.com/portal/clientportal.gw.zip && \
    unzip clientportal.gw.zip && rm clientportal.gw.zip

RUN mkdir -p api_gateway/root

COPY conf.yaml api_gateway/root/conf.yaml
COPY run_gateway.sh /app/run_gateway.sh
COPY healthcheck.sh /usr/local/bin/healthcheck.sh
# tickler.sh is deliberately NOT copied — see run_gateway.sh for why the
# in-container tickler was removed on 2026-08-06.

RUN chmod +x /app/run_gateway.sh /usr/local/bin/healthcheck.sh

EXPOSE 5055

ENTRYPOINT ["/app/run_gateway.sh"]
