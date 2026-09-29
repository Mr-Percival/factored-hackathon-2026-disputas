# Reporte de calidad de datos

Base: `data\serving_full.duckdb` · corridas registradas: 1

## Completitud y cuarentena

| Tabla | Filas cargadas | Documentadas | Completitud | En cuarentena |
|---|---|---|---|---|
| customers | 150,000 | 150,000 | 100.0% | 0 |
| products | 400,000 | 400,000 | 100.0% | 0 |
| transactions | 4,425,008 | 5,000,000 | 88.5% | 0 |
| complaints | 67,095 | 80,000 | 83.9% | 0 |

## Checks fallidos (cuarentena)

Ninguna fila violó el contrato.

## Advertencias del contrato (no bloquean la carga)

| Tabla | Advertencia | Filas | % |
|---|---|---|---|
| transactions | `mexico_without_mxn` | 2,146,309 | 48.5% |

## Frescura

Política: alerta si la última partición tiene más de 2 días de atraso respecto de la fecha de referencia (`as_of` en `config/policy.yaml`).

| Tabla | Última partición |
|---|---|
| transactions | 2026-06-17 |
| complaints | 2026-06-17 |

## Nulos en columnas opcionales

| Tabla | Columna | % nulos |
|---|---|---|
| transactions | merchant_name | 76.7% |
| transactions | merchant_category | 76.8% |
| transactions | transaction_city | 10.0% |
| transactions | fraud_score | 20.0% |
| complaints | subcategory | 10.0% |
| complaints | affected_product_id | 33.6% |

## Linaje: corridas

| run_id | Tabla | Archivos nuevos | Filas in | Cargadas | Cuarentena | Duplicados en lote |
|---|---|---|---|---|---|---|
| 20260928T212415-11d1a0 | customers | 1 | 150,000 | 150,000 | 0 | 0 |
| 20260928T212415-11d1a0 | products | 1 | 400,000 | 400,000 | 0 | 0 |
| 20260928T212415-11d1a0 | transactions | 1,097 | 4,425,008 | 4,425,008 | 0 | 0 |
| 20260928T212415-11d1a0 | complaints | 1,097 | 67,095 | 67,095 | 0 | 0 |

Normalizaciones aplicadas: `{'country_aliases': {'Mexico': 'México'}}`

Huella de la entrega en la última corrida (cambia si el organizador regenera los datos): customers=`c5fcfddc9ed220fa`, products=`151a201d660a17b5`, transactions=`f8547ae41edd4ab7`, complaints=`3d3ddc541abc6c6b`
