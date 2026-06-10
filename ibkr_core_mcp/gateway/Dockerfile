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
COPY tickler.sh /app/tickler.sh

RUN chmod +x /app/run_gateway.sh /usr/local/bin/healthcheck.sh /app/tickler.sh

EXPOSE 5055

ENTRYPOINT ["/app/run_gateway.sh"]
