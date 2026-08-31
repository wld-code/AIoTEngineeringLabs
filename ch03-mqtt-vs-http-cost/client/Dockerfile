# Lab 3 — the client container. Runs the MQTT/HTTP client AND the packet
# capture for every test, both inside the same network namespace, so the
# capture sees exactly this container's own traffic — no host loopback
# interface, no "which interface is lo on this OS" question, works
# identically under Docker Engine on Linux and Docker Desktop on macOS.
#
# Build context is the lab root (see docker-compose.yml: `context: .,
# dockerfile: client/Dockerfile`) so analyze_capture.py can be copied in
# from one canonical location instead of duplicated.
FROM python:3.12-alpine

RUN apk add --no-cache tcpdump

WORKDIR /app
COPY client/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY analyze_capture.py .
COPY client/telemetry_client.py .
COPY client/run_one_test.py .

# NET_RAW + NET_ADMIN (granted via docker-compose cap_add) let tcpdump
# capture without running the container as root.
CMD ["sleep", "infinity"]
