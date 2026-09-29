# Capacidad del agente (línea base de reglas, sin LLM)

> Medido el 2026-09-28 con `python scripts/loadtest.py` sobre la base serving **real** (150k clientes, 400k productos,
> 4.4M transacciones, 67k reclamos). Resultados crudos: [`capacity_results.json`](capacity_results.json).
> **No incluye LLM**: la latencia y el costo del modelo salen de la evaluación (#12); aquí solo hay una estimación
> rotulada como tal (sección 5).

## 1. Cómo se midió

- **Carga:** N trabajadores simulan conversaciones completas de clientes reales elegidos al azar (2000 clientes con
  una transacción disputable en los últimos 90 días). Mezcla: disputa por monto 40% · disputa ambigua → elige
  opción → confirma 25% · bloqueo de tarjeta 20% · fuera de alcance 15%; ~20% en portugués. El trabajador contesta
  lo que pide el agente ("la 1", "sí"), hasta 4 turnos por conversación. 20 s por nivel, 2 s de calentamiento.
- **Modos:** `threads` = un proceso con un solo `Agent` compartido por N hilos (así corre una réplica);
  `processes` = N procesos, cada uno con su `Agent` (= N réplicas sin estado leyendo la misma base).
- **Métricas:** turnos/s; latencia por turno p50/p95/p99; latencia por nodo y por herramienta **desde la traza del
  grafo**; *overhead* = turno − suma de nodos (LangGraph, checkpointer, espera del GIL); CPU del proceso por turno;
  tasa de error (excepción no controlada); memoria pico (working set).
- **Máquina:** laptop Intel Core i5-10300H (4 núcleos / 8 hilos, 2.5 GHz), 31.8 GB RAM, NVMe SSD, Windows 11,
  Python 3.12.2, DuckDB 1.5.6, LangGraph 1.2.12.

**Caveats (importantes):** una sola máquina y **compartida**: durante las corridas otros procesos del equipo (pipeline,
evals, tests) tenían la CPU cerca del 100%. Las cifras absolutas son pesimistas y ruidosas (el p50 con 1 hilo
varió de 25 a 270 ms entre corridas); la CPU por turno es la métrica más estable. Sin red entre agente y base, sin
TLS, sin LLM, ops en memoria. Es una prueba de capacidad del código, no del sistema de producción.

## 2. Resultados

**A. `main` antes de este PR** (una conexión DuckDB compartida entre hilos, sin índices)

| hilos | turnos/s | p50 ms | p95 ms | p99 ms | error |
|---|---|---|---|---|---|
| 1 | 4.0 | 270 | 559 | 672 | 0.0% |
| 4 | 5.6 | 614 | 977 | 1083 | **11.0%** |
| 8 | 9.9 | 632 | 1602 | 1908 | **6.9%** |
| 16 | 8.3 | 1638 | 3063 | 3514 | **8.8%** |
| 32 | 11.3 | 2591 | 3575 | 4122 | **8.0%** |

Los errores (`KeyError: 'product_status'`, `'customer_id'`…) son resultados de una consulta leídos por otro hilo.
**El caso grave no es el error sino el que no falla:** un cliente puede recibir filas de otro. Lo reproduce
`tests/test_concurrency.py` (en `main`, CLI-BETO recibió `T-CAN-1`, la transacción del cliente señuelo).
Corrida en el momento de más carga de la máquina: comparar con B/C solo la tasa de error, no la latencia.

**B. Cursor por hilo, sin índices** (código final, base sin índices)

| hilos | turnos/s | p50 | p95 | p99 | error | CPU ms/turno | `search_transactions` p50 |
|---|---|---|---|---|---|---|---|
| 1 | 14.3 | 58 | 164 | 242 | 0% | 137 | 61 ms |
| 4 | 13.7 | 224 | 723 | 899 | 0% | 133 | 81 ms |
| 8 | 7.9 | 944 | 1334 | 1548 | 0% | 131 | 104 ms |
| 16 | 14.8 | 810 | 2229 | 2553 | 0% | 128 | 439 ms |
| 32 | 16.4 | 1509 | 4835 | 5599 | 0% | 142 | 164 ms |

**C. Cursor por hilo + índices por `customer_id`** (código final de este PR) — **una réplica**

| hilos | turnos/s | p50 | p95 | p99 | error | CPU ms/turno | `search_transactions` p50 | RSS |
|---|---|---|---|---|---|---|---|---|
| 1 | 17.0 | 36 | 176 | 246 | 0% | 32 | 10 ms | 650 MB |
| 4 | 41.9 | 86 | 160 | 240 | 0% | 30 | 13 ms | 797 MB |
| **8** | **61.3** | **117** | **233** | **305** | 0% | 25 | 13 ms | 903 MB |
| 16 | 54.4 | 259 | 575 | 696 | 0% | 26 | 14 ms | 977 MB |
| 32 | 20.3 | 1443 | 2101 | 2416 | 0% | 25 | 12 ms | 1016 MB |

**D. Réplicas en procesos** (índices, un `Agent` por proceso)

| réplicas | turnos/s | p50 | p95 | p99 | error | RSS total |
|---|---|---|---|---|---|---|
| 1 | 31.6 | 25 | 75 | 115 | 0% | 0.7 GB |
| 4 | 46.4 | 78 | 165 | 221 | 0% | 2.4 GB |
| 8 | 97.5 | 72 | 158 | 229 | 0% | 4.9 GB |

**Por nodo y herramienta** (C, 1 hilo, p50 / p95 ms): `find_transaction` 10.3 / 17.2 · `decide` 10.8 ·
`search_transactions` 10.3 / 17.2 · `list_cards` 4.6 / 8.3 · `block_card` 7.1 / 12.2 · `open_dispute` 6.6 / 10.7 ·
`dispute_history` 3.3 / 6.5 · `get_transaction` 3.3 / 5.9 · `get_profile` 1.4 / 2.9 · `guard`, `understand`,
`respond`, `handoff` < 0.3. Cero reintentos y cero errores en todas las corridas B, C y D.

## 3. Cuellos de botella

1. **Conexión DuckDB compartida entre hilos → fuga entre clientes (corregido).** Un `DuckDBPyConnection` no es seguro
   entre hilos. `BankTools` ahora abre un cursor por hilo (`_ro_c`, `_ops_c`). Test: `tests/test_concurrency.py`.
2. **Recorrido completo de `transactions` por turno (corregido).** No había índices secundarios. `EXPLAIN ANALYZE`
   de `search_transactions`: `TABLE_SCAN · Sequential Scan` sobre 4.4M filas (~45 ms aislado). Crear un índice no
   basta: con `customer_id = ?` junto a otros filtros y `ORDER BY … LIMIT`, DuckDB 1.5 sigue recorriendo la tabla.
   Solución: el pipeline crea índices ART en `customer_id` (`pipeline.LOOKUP_INDEXES`, ~12 s sobre la base completa)
   y las consultas aíslan `customer_id = ?` en una CTE `MATERIALIZED`. Medido aislado sobre una copia de la base:

   | consulta | antes | después |
   |---|---|---|
   | `search_transactions` | 45 ms | 3.5 ms |
   | `list_cards` | 15 ms | 3.3 ms |
   | propiedad de tarjeta en `block_card` | 16 ms | 1.4 ms |

   Efecto en el agente: CPU por turno de ~135 a ~28 ms (4.8×); throughput máximo de una réplica de ~16 a ~61 turnos/s.
3. **Ahora el límite es Python/LangGraph, no la base.** Con índices, el *overhead* del grafo (≈ 14–25 ms por turno
   con un hilo) pesa más que todas las herramientas juntas, y más hilos no ayudan pasado 8: el GIL serializa el
   trabajo en Python (con 32 hilos el overhead p50 sube a 1.4 s). El perfil (`cProfile`) muestra que buena parte es
   `ThreadPoolExecutor.submit` del runner de LangGraph (crea hilos por invocación para escribir checkpoints). Una
   prueba A/B con `graph.invoke(..., durability="exit")` bajó el overhead p50 de ~22–84 ms a ~14 ms. **No se aplicó**
   (cambia cuándo se guarda el estado y `graph.py` lo están editando otros PR); queda como recomendación.
4. **Memoria:** ~0.6–1 GB por réplica, casi todo caché de DuckDB sobre la base de 665 MB. Escalar en procesos
   multiplica la memoria (8 réplicas = 4.9 GB); en producción la base no vive dentro de la réplica.

## 4. Límites de capacidad (lo que se puede afirmar)

- **Una réplica (1 proceso, 8 hilos):** ~60 turnos/s con p95 ≈ 230 ms sin LLM. Con más de 16 hilos la latencia se
  dispara: **no pasar de 8–16 hilos por proceso**; escalar con procesos o réplicas.
- **8 réplicas en esta laptop:** ~98 turnos/s, p95 ≈ 160 ms. Con ~2.3 turnos por conversación, ~40 conversaciones
  nuevas por segundo, holgadamente más que el volumen de reclamos del dataset (67k reclamos en total).
- **Techo por núcleo** (CPU por turno ≈ 25–32 ms): ~30–40 turnos/s por núcleo sin LLM.

## 5. Estimación con LLM (ESTIMACIÓN, no medición)

Supuestos, a reemplazar por los números de #12: router con salida estructurada ≈ 0.6–1.2 s p50 y 2–3 s p95;
writer ≈ 0.8–1.5 s p50 y 2–3 s p95 (modelo rápido, prompt de ~1k tokens, 100–200 tokens de salida); como máximo
2 llamadas por turno, en serie.

| | p50 por turno | p95 por turno |
|---|---|---|
| Reglas (medido, C con 8 hilos) | 0.12 s | 0.23 s |
| Reglas + router + writer (estimado) | **≈ 1.5–2.8 s** | **≈ 4–6 s** (las colas no se suman linealmente; cota pesimista) |

Con LLM el turno pasa a estar dominado por espera de red: los hilos esperando no retienen el GIL, así que una
réplica aguanta muchas más conversaciones en vuelo (ley de Little: 60 turnos/s × 2 s ≈ 120 turnos en vuelo), y el
límite real pasa a ser **la cuota del proveedor** (tokens/min y solicitudes/min) y el costo. Hay que medirlo (#12)
y probar la carga con LLM real antes de producción ([`docs/operations.md`](../docs/operations.md), sección 8).

## 6. Reproducir

```bash
python scripts/loadtest.py                                  # barrido 1,4,8,16,32 hilos sobre data/serving.duckdb
python scripts/loadtest.py --mode processes --concurrency 1,4,8
python scripts/loadtest.py --concurrency 8 --seconds 60 --out reports/capacity_results.json   # agrega una corrida
```

Una base construida antes de este PR no tiene los índices: `python -m bankagent.pipeline` sobre la misma base los
crea sin recargar datos (no hay archivos nuevos; solo corre `CREATE INDEX IF NOT EXISTS`, ~12 s).
