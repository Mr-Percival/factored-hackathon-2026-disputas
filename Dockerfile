# syntax=docker/dockerfile:1
# Demo web en un solo contenedor: la SPA compilada (web/dist) la sirve el mismo proceso FastAPI.
#
#   docker build -t bankagent-web .
#   docker run --rm -p 8000:8000 bankagent-web          # http://localhost:8000
#
# Base de datos: si existe docker/demo-db/demo.duckdb al construir (base liviana de clientes reales, #28; ver
# docker/demo-db/README.md) se hornea en la imagen y se usa por defecto; si no, la API construye al arrancar la
# base mínima del fixture etiquetado. BANKAGENT_DB en tiempo de ejecución siempre gana.

# ---------------------------------------------------------------- 1) build de la SPA
FROM node:22-alpine AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ---------------------------------------------------------------- 2) runtime Python
FROM python:3.12-slim AS runtime
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PORT=8000
WORKDIR /app

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin app

# Instalación editable: policy.py y la API resuelven config/ y web/dist relativos a /app.
COPY pyproject.toml ./
COPY src/ src/
COPY config/ config/
COPY docs/demo/demo_customers.json docs/demo/demo_customers.json
# Router aprendido lite (ADR 0009): 0.2 MB + numpy. Se activa con BANKAGENT_ROUTER=embeddings; el full no entra.
COPY models/intent_router_lite/ models/intent_router_lite/
RUN pip install -e ".[api,ml]"

COPY docker/ docker/
COPY --from=web /web/dist web/dist
RUN chmod 0555 docker/entrypoint.sh

USER app
EXPOSE ${PORT:-8000}
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD ["python", "-m", "bankagent.app_health"]

# Un solo worker A PROPÓSITO: la conversación (InMemorySaver), las sesiones y el almacén ops viven en la memoria
# del proceso; con varios workers el "sí" de la confirmación podría caer en otro proceso (ADR 0007).
CMD ["/app/docker/entrypoint.sh"]
