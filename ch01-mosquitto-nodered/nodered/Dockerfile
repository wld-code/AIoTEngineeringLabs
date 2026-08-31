# Pinned to the 3.1 line for reproducibility — the same image Chapter 5 uses.
FROM nodered/node-red:3.1

# Pre-install node-red-contrib-redis so the imported flow's redis-config /
# redis-command nodes resolve on first boot. Pinned: this is the ioredis-based
# 1.4.x line whose node types (redis-config, redis-command) the flow relies on.
RUN npm install --no-audit --no-fund node-red-contrib-redis@1.4.0
