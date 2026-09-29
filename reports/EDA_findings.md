# EDA — hallazgos (2026-09-28)

Fuente: `data/raw` (S3 `data/`, descargado completo salvo `digital_events` y `campaign_sends`, de los que se bajaron 30 particiones diarias).
Scripts: `scripts/eda.py` → `reports/eda_output.txt`, `scripts/eda_checks.py` → `reports/eda_checks.txt`.

## 1. Demanda y por qué importa el flujo de disputas
| Categoría | % contactos | FCR | Requiere seguimiento | Duración mediana |
|---|---|---|---|---|
| Transaccional | 35.0% | 91.5% | 22.1% | 205 s |
| Producto | 22.0% | 89.6% | 23.8% | 263 s |
| **Queja** | 17.1% | **43.6%** | **63.0%** | **431 s** |
| Técnico | 15.0% | 69.9% | 40.6% | 360 s |
| Comercial | 8.0% | 65.2% | 44.5% | 540 s |
| Retención | 3.0% | 60.2% | 49.1% | 478 s |

- Las quejas son el peor segmento operativo: FCR de 43.6% contra 91.5% en transaccionales y el doble de duración.
- En PQR (67k casos), las subcategorías principales son **"Cargo no reconocido" (12.3k)** y **"Cobro indebido" (12.2k)**, el 36% del total. El 20% incumple SLA, la mediana de resolución es 16 días y el 77% sigue sin resolución registrada.
- Fraude: `is_fraud` = 0.1% (3.4k positivos con score). `fraud_score` separa bien (AUC ≈ 0.85; media 49.5 en fraude contra 15.0 en no fraude). El resto de variables (canal, monto, hora, compra en el extranjero) casi no aportan señal.
- Hay unas 40k transacciones en **Brasil** de clientes de MX/CO/AR, un escenario natural para la demo en portugués ("cargo no reconocido en Brasil").

## 2. Limitaciones de datos (se reportan, no se ocultan)
1. **Las transcripciones no sirven para etiquetar intención.** Solo hay 42 textos distintos del cliente y 546 textos completos. El texto no depende de la categoría: "consultar el saldo de mi tarjeta" aparece igual en Queja, Técnico, Retención, etc. `detected_intents` = `consulta_general` en el 100% de los casos y `main_topics` = categoría. Entrenar un clasificador de intención con esto sería inválido.
2. `contact_reason` es idéntico a `reason_category` (6 valores); no hay motivo detallado.
3. Las descripciones de quejas son plantillas ("Queja relacionada con fees"). `origin_interaction_id` está 100% nulo, así que no se pueden unir quejas con llamadas.
4. **Moneda en México:** no hay ninguna transacción ni producto en MXN; todo lo mexicano está en USD. Además el país aparece como "México" y "Mexico".
5. `amount_usd` está nulo en el 57% de las filas y `merchant_name` en el 77%.
6. **No se encontraron duplicados** (ni por PK ni por fila completa ni casi duplicados), aunque la documentación dice ~2%. Queda pendiente revisar `data_backup_20260831/`, que difiere en tamaños.
7. Los conteos son menores a los documentados: interacciones 686k (no 800k), transacciones 4.43M (no 5M), transcripciones 171k (no 200k).
8. `process_date` es 1 día **anterior** a la fecha del evento en ~25% de las filas (probable desfase de zona horaria), así que no son llegadas tardías.
9. Hay distribuciones uniformes típicas de datos sintéticos: volumen plano por hora del día y KPIs idénticos por país, segmento y acento.
10. **Acento:** que el agente use el mismo acento que el cliente no cambia los resultados (FCR 76.68% contra 76.59%; CSAT 2.766 contra 2.762). No hay base para rutear por acento.
11. Todo el texto está en español; **no hay portugués**.

12. **El bucket trae dos generaciones distintas del dataset.** `data_backup_20260831/` no es una versión anterior de `data/`: los IDs de clientes, productos y transacciones casi no se solapan, y las 67.095 quejas conservan su ID pero **todas** apuntan a otro cliente. Además, el backup tiene transacciones solo hasta 2024-09 (453 particiones). No sirve como entrega incremental real; la actualización se demuestra con el fixture de prueba. Detalle: [`snapshot_diff.md`](snapshot_diff.md).
    → Como el organizador ya regeneró los datos una vez, el manifiesto registra una **huella de la entrega** por tabla. Si cambia, los artefactos que referencian IDs (casos de evaluación, guion de demo) se regeneran desde la base.

## 3. Implicaciones de diseño
- **Flujo:** intake de cargo no reconocido / cobro indebido; es el mayor volumen de PQR y el peor FCR.
- **Componente aprendido:** *ranking de transacciones* (descripción del cliente → transacción disputada). Las etiquetas son válidas por construcción: las consultas se generan a partir de transacciones reales retenidas, en es y pt, con paráfrasis. Se compara contra una línea base de reglas (la más reciente o el monto exacto). No se usa un clasificador sobre transcripciones por la limitación 1.
- **Política:** el umbral de `fraud_score` para escalar se elige con la curva precisión/recall del set de entrenamiento (split temporal).
- **Equidad:** el mismo caso en variantes de dialecto (MX/CO/AR/pt-BR) debe producir la misma decisión. No se enruta por acento (limitación 10).
- **Conjunto conversacional de evaluación:** generado por el equipo y etiquetado explícitamente como tal, no como tráfico real.
