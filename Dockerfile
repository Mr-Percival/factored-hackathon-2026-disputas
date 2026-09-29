# Demo web (Streamlit). Sin BANKAGENT_DB construye una base mínima desde el fixture al arrancar.
#   docker build -t bankagent-demo .
#   docker run --rm -p 8501:8501 bankagent-demo
#   docker run --rm -p 8501:8501 -v "$PWD/data:/data:ro" -e BANKAGENT_DB=/data/demo.duckdb bankagent-demo
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8501

# uid 1000: lo exige Hugging Face Spaces y sirve igual en Render / local
RUN useradd --create-home --uid 1000 app
WORKDIR /app

COPY --chown=app:app pyproject.toml README.md ./
COPY --chown=app:app src ./src
COPY --chown=app:app config ./config
COPY --chown=app:app app ./app
COPY --chown=app:app .streamlit ./.streamlit
RUN pip install -e ".[ui]"

USER app
EXPOSE 8501

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD python -m bankagent.app_health --url "http://localhost:${PORT}" || exit 1

# PORT lo inyectan Render / HF Spaces; por defecto 8501
CMD streamlit run app/streamlit_app.py --server.port="${PORT}" --server.address=0.0.0.0 --server.headless=true
