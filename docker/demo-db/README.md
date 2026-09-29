# Base de demo para la imagen

Si al construir la imagen existe `docker/demo-db/demo.duckdb`, se copia a la imagen y la API la usa por defecto
(con los escenarios de clientes reales de `docs/demo/demo_customers.json`). Si no existe, la API arranca con el
fixture etiquetado (datos inventados, `config/demo_scenarios.json`).

```bash
python -m bankagent.pipeline --raw data/raw --out data/demo/demo.duckdb \
    --sample-customers 500 --include-customers docs/demo/demo_customers.json
cp data/demo/demo.duckdb docker/demo-db/demo.duckdb
docker build -t bankagent-web .
```

El archivo `*.duckdb` está en `.gitignore`: **nunca se commitea** (los datos del organizador no se suben al repo).
Es una base derivada de solo lectura, sin columnas de PII (el pipeline no las carga) y de ~6 MB.
