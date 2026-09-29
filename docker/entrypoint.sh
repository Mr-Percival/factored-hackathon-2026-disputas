#!/bin/sh
# Arranque del contenedor de la demo web. Un worker (estado en memoria: ver ADR 0007).
set -eu

if [ -z "${BANKAGENT_DB:-}" ] && [ -f /app/docker/demo-db/demo.duckdb ]; then
  export BANKAGENT_DB=/app/docker/demo-db/demo.duckdb
fi

# IP real para las cuotas por IP: la última entrada de X-Forwarded-For, la que agrega el proxy de la plataforma
# (la primera la escribe el cliente y se puede inventar; red team #33). Ver bankagent/api/deps.py::client_ip.
export BANKAGENT_TRUSTED_PROXY_HOPS="${BANKAGENT_TRUSTED_PROXY_HOPS:-1}"

# --proxy-headers: detrás del proxy TLS de la plataforma, el esquema https (cookie Secure, HSTS) y la IP del
# cliente (rate limit) salen de X-Forwarded-*. FORWARDED_ALLOW_IPS debe limitarse al proxy si se expone directo.
exec uvicorn bankagent.api.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8000}" \
  --workers 1 \
  --proxy-headers \
  --forwarded-allow-ips "${FORWARDED_ALLOW_IPS:-*}" \
  --no-server-header
