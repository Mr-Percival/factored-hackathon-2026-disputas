# Replay de quejas históricas + modo sombra

> **SIMULACIÓN OFFLINE — no es una medición de producción.** Quejas reales del dataset (sintético) del organizador, convertidas en conversaciones con un cliente **simulado** y pasadas por el agente real (reglas + plantillas, sin LLM). La transacción disputada se **infiere** con una regla (las quejas no la traen), así que el agente se mide contra esa regla, no contra una verdad conocida. Las proyecciones de negocio están aparte, en la sección 8, rotuladas **PROYECCIÓN**.

Generado por `python -m bankagent.evals.replay --db serving_full.duckdb --n 1000 --seed 7 --history-db bank.duckdb` · commit `09e2d0f` · política `2026-09-29.1` · 2026-09-28. Detalle en la sección 10.

## Resumen — SIMULACIÓN

| Métrica (SIMULACIÓN) | Valor [IC 95% Wilson] | k | n |
|---|---|---|---|
| Quejas en la muestra | 1 000 |  |  |
| Con transacción plausible (automatización intentada) | 62.4% [59.4%–65.3%] | 624 | 1 000 |
| **Resolución automática segura** (del total) | 33.3% [30.4%–36.3%] | 333 | 1 000 |
| Resolución automática segura (de las intentadas) | 53.4% [49.4%–57.2%] | 333 | 624 |
| Derivado a humano (handoff) | 26.8% [24.1%–29.6%] | 268 | 1 000 |
| Rechazada por política (D02–D05) | 2.3% [1.5%–3.4%] | 23 | 1 000 |
| Cargo no identificado en la conversación | 0.0% [0.0%–0.4%] | 0 | 1 000 |
| Decisión sobre una transacción distinta a la emparejada | 0.0% [0.0%–0.4%] | 0 | 1 000 |
| Sin transacción plausible (iría a un humano, no se conversa) | 37.6% [34.7%–40.6%] | 376 | 1 000 |
| Acciones inseguras (otro cargo, sin confirmación o sin verificar) | 0.0% [0.0%–0.4%] | 0 | 1 000 |
| Turnos del cliente por caso (p50 / p95) | 2 / 3.0 |  | 624 |
| Latencia por turno p50 / p95 (local, sin LLM) | 38 / 118 ms |  | 1 036 |

Lectura: *resolución automática segura* = el agente encontró el cargo emparejado, pidió confirmación, abrió la disputa (y bloqueó la tarjeta si estaba activa), ambas acciones verificadas releyendo el estado, **y** la política evaluada por separado sobre ese cargo a la fecha de la queja dice `auto_with_confirmation`. Resolver = abrir la disputa en el primer contacto; el resultado final de la disputa (abono o no) no se simula.

## 1. Marco muestral

- **Marco:** todas las quejas con subcategoría *Cargo no reconocido* o *Cobro indebido* en la base serving: **24 491** quejas, creadas entre 2023-06-17 y 2026-06-18.
- **Muestra:** 1 000 quejas, estratificada por país × segmento × case_type (asignación proporcional con restos mayores; dentro de cada estrato, al azar con `seed=7`). Se incluyen las quejas sin transacción plausible: su proporción es un resultado.

| País | Marco | % marco | Muestra | % muestra |
|---|---|---|---|---|
| México | 12 099 | 49.4% | 494 | 49.4% |
| Colombia | 7 515 | 30.7% | 308 | 30.8% |
| Argentina | 4 877 | 19.9% | 198 | 19.8% |

| Segmento | Marco | % marco | Muestra | % muestra |
|---|---|---|---|---|
| Basic | 14 689 | 60.0% | 600 | 60.0% |
| Plus | 6 130 | 25.0% | 250 | 25.0% |
| Premium | 2 461 | 10.0% | 101 | 10.1% |
| Student | 1 211 | 4.9% | 49 | 4.9% |

| case_type | Marco | % marco | Muestra | % muestra |
|---|---|---|---|---|
| Complaint | 14 818 | 60.5% | 604 | 60.4% |
| Claim | 6 040 | 24.7% | 247 | 24.7% |
| Request | 2 444 | 10.0% | 100 | 10.0% |
| Suggestion | 1 189 | 4.9% | 49 | 4.9% |

| Subcategoría | Marco | % marco | Muestra | % muestra |
|---|---|---|---|---|
| Cargo no reconocido | 12 297 | 50.2% | 502 | 50.2% |
| Cobro indebido | 12 194 | 49.8% | 498 | 49.8% |

## 2. Regla de emparejamiento queja → transacción y cobertura

Las quejas **no** traen la transacción (`origin_interaction_id` 100% nulo, descripción de plantilla). La regla, escalonada y documentada en `src/bankagent/evals/matching.py`:

- **Conjunto de candidatas:** transacciones del mismo cliente, de tipo disputable (Purchase, Withdrawal, Payment, Transfer, Adjustment; el mismo filtro que usa el agente) y con fecha en `[creation_date − 60 días, creation_date]`.
- **R1:** `claimed_amount` presente, misma moneda y a ±10% → la de monto más cercano.
- **R2:** la más reciente *Approved* del tipo esperado (Cargo no reconocido: Purchase/Withdrawal; Cobro indebido: Adjustment/Purchase).
- **R3:** la más reciente *Approved* de cualquier tipo disputable. **R4:** la más reciente de cualquier estado.
- **Sin match:** no hay candidatas → en operación iría a un humano; no se simula conversación.

| Regla (muestra, n=1000) | % [IC 95%] | k |
|---|---|---|
| R1 · monto reclamado ±10% | 0.4% [0.2%–1.0%] | 4 |
| R2 · más reciente Approved del tipo esperado | 35.2% [32.3%–38.2%] | 352 |
| R3 · más reciente Approved (cualquier tipo) | 24.5% [21.9%–27.3%] | 245 |
| R4 · más reciente (cualquier estado) | 2.3% [1.5%–3.4%] | 23 |
| Sin match | 37.6% [34.7%–40.6%] | 376 |

**Cobertura en el marco completo según la ventana** (n=24 491; candidatas = transacciones disputables del cliente en la ventana; *1* = identificación directa, *2–5* = el agente mostraría opciones, *>5* = muy ambiguo):

| Ventana | Con ≥1 candidata | 0 | 1 | 2–5 | >5 |
|---|---|---|---|---|---|
| 7 días | 14.7% | 85.3% | 13.2% | 1.5% | 0.0% |
| 15 días | 27.9% | 72.1% | 21.8% | 6.1% | 0.0% |
| 30 días | 45.4% | 54.6% | 28.2% | 17.1% | 0.1% |
| 60 días | 64.1% | 35.9% | 26.6% | 35.6% | 1.8% |

Hallazgos sobre los campos de enlace (marco completo):

- `affected_product_id` está presente en 16 257 quejas (66.4%), pero **pertenece al cliente de la queja en 0** de ellas. Es un campo aleatorio respecto del cliente, así que la regla no lo usa (exigirlo dejaría 0% de cobertura).
- 2 419 quejas (9.9%) son de clientes **sin ninguna transacción** en la base: nunca pueden emparejarse.
- `claimed_amount` (en la muestra, 324 quejas lo traen): R1 empareja 4 (1.2%); con montos de **otras** quejas al azar (control, 20 sorteos por queja) empareja en promedio 1.2 (0.4%). En el dataset el monto reclamado tiene la misma distribución (~0–5.000) en COP, ARS, USD y MXN, su moneda no depende del país del cliente y no hay transacciones en MXN: el monto reclamado **casi no aporta información** para encontrar el cargo, y los pocos R1 pueden ser coincidencias.

## 3. Método de la simulación

- **Agente:** `build_agent(db, router="rules", writer="templates")`, uno nuevo por caso y un hilo nuevo por conversación; login simulado (`IdentityService`), sin LLM ni red. Disputas y bloqueos se reinician entre casos.
- **A la fecha de la queja:** cada caso usa `PolicyEngine(as_of=creation_date)` (así D05 — 120 días — y las fechas relativas "ayer" / "la semana pasada" se resuelven contra el día de la queja, no contra el `as_of` del YAML, 2026-06-17). La búsqueda de movimientos no ve transacciones posteriores a la queja y H04 se calcula con las quejas del cliente hasta esa fecha (`PointInTimeTools`).
- **Mensaje del cliente (generado por el equipo):** menciona monto y/o fecha y el país si el cargo fue en el extranjero, nunca IDs; dialecto por país del cliente (MX, CO, AR con voseo). Estilos: monto + fecha (50%), solo monto (25%), solo fecha (25%); 40% de los montos ≥ 100 se dicen redondeados ("unos $1.300"). Una submuestra (20% de los casos emparejados) se corre también en **pt-BR: traducción hecha por el equipo** (el dataset no tiene portugués).
- **Cliente simulado:** confirma ("sí" / "sim") solo si el cargo propuesto es el emparejado (si no, dice "no, ese no es"); si le muestran opciones, elige la emparejada comparando IDs (simula que reconoce su cargo); si no aparece o le piden más datos, da **una vez** el monto exacto y la fecha completa. Si aun así no aparece → *no identificado*. Tope de 6 turnos.

## 4. Métricas — SIMULACIÓN (n=1000, una conversación por queja en su dialecto)

| Resultado | % del total [IC 95%] | k |
|---|---|---|
| Resolución automática segura (disputa abierta y verificada) | 33.3% [30.4%–36.3%] | 333 |
| Derivado a humano (handoff) | 26.8% [24.1%–29.6%] | 268 |
| Rechazada por política (D02–D05) | 2.3% [1.5%–3.4%] | 23 |
| Cargo no identificado en la conversación | 0.0% [0.0%–0.4%] | 0 |
| Decisión sobre una transacción distinta a la emparejada | 0.0% [0.0%–0.4%] | 0 |
| Sin transacción plausible (iría a un humano, no se conversa) | 37.6% [34.7%–40.6%] | 376 |

| Handoff por regla (primera que decide) | % del total | k |
|---|---|---|
| H02_high_amount | 10.6% [8.8%–12.7%] | 106 |
| H01_customer_not_active | 9.2% [7.6%–11.2%] | 92 |
| H04_repeat_complainer | 6.9% [5.5%–8.6%] | 69 |
| H03_fraud_signal | 0.1% [0.0%–0.6%] | 1 |

| Rechazo / informa por regla | % del total | k |
|---|---|---|
| D02_declined_not_charged | 1.1% [0.6%–2.0%] | 11 |
| D04_pending | 0.7% [0.3%–1.4%] | 7 |
| D03_already_reversed | 0.5% [0.2%–1.2%] | 5 |

**Por qué no se identificó el cargo** (conversaciones que terminaron en *no identificado*):

| Motivo | es | pt-BR |
|---|---|---|
| El router no reconoció el pedido (confianza < 0,6) | 0 | 1 |

Al revisar las transcripciones de esos casos (`data/replay/cases.jsonl`) aparecen dos causas del router de reglas (`understanding.py`) que se combinan; son hallazgos del replay y no se corrigen en este cambio: (1) la lista de palabras clave de disputa tiene `"no reconheco"` en vez de `"nao reconheco"`, así que "não reconheço" no cuenta como pedido de disputa en portugués; (2) el comercio **"Taxi Seguro"** contiene `seguro`, palabra de *fuera de alcance*: si el mensaje tiene una sola palabra de disputa, empata, la confianza baja a 0,5 y el agente vuelve a preguntar.

Reglas que se cumplen sobre el cargo emparejado (pueden ser varias por caso): D02_declined_not_charged: 11, D03_already_reversed: 5, D04_pending: 7, H01_customer_not_active: 99, H02_high_amount: 133, H03_fraud_signal: 1, H04_repeat_complainer: 108.

- **Aclaraciones:** 12.7% [10.3%–15.5%] de las conversaciones intentadas necesitaron al menos un turno de aclaración (pedir datos u opciones); media 0.13 por caso.
- **Turnos del cliente:** media 1.66, p50 2, p95 3.0, máx 3.
- **Latencia** (proceso local, DuckDB con 24 491 quejas y la tabla completa de transacciones, sin LLM): por turno p50 38 ms / p95 118 ms; por caso p50 64 ms / p95 201 ms. No incluye red ni LLM; ver `reports/capacity.md` para carga concurrente.

**Por país**

| País | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| Argentina | 198 | 39.4% [32.9%–46.3%] | 22.2% | 3.0% | 0.0% | 35.4% |
| Colombia | 308 | 32.5% [27.5%–37.9%] | 23.7% | 2.3% | 0.0% | 41.6% |
| México | 494 | 31.4% [27.4%–35.6%] | 30.6% | 2.0% | 0.0% | 36.0% |

**Por segmento**

| Segmento | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| Basic | 600 | 33.7% [30.0%–37.5%] | 27.2% | 2.2% | 0.0% | 37.0% |
| Plus | 250 | 36.4% [30.7%–42.5%] | 26.0% | 2.8% | 0.0% | 34.8% |
| Premium | 101 | 26.7% [19.1%–36.1%] | 28.7% | 2.0% | 0.0% | 42.6% |
| Student | 49 | 26.5% [16.2%–40.3%] | 22.4% | 2.0% | 0.0% | 49.0% |

**Por case_type**

| case_type | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| Claim | 247 | 33.2% [27.6%–39.3%] | 30.0% | 2.0% | 0.0% | 34.8% |
| Complaint | 604 | 33.9% [30.3%–37.8%] | 26.7% | 2.2% | 0.0% | 37.3% |
| Request | 100 | 31.0% [22.8%–40.6%] | 23.0% | 4.0% | 0.0% | 42.0% |
| Suggestion | 49 | 30.6% [19.5%–44.5%] | 20.4% | 2.0% | 0.0% | 46.9% |

**Por subcategoría**

| Subcategoría | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| Cargo no reconocido | 502 | 32.7% [28.7%–36.9%] | 30.1% | 1.8% | 0.0% | 35.5% |
| Cobro indebido | 498 | 33.9% [29.9%–38.2%] | 23.5% | 2.8% | 0.0% | 39.8% |

**Por regla de match**

| Regla de match | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| R1_amount | 4 | 0.0% [0.0%–49.0%] | 100.0% | 0.0% | 0.0% | 0.0% |
| R2_type_approved | 352 | 69.9% [64.9%–74.4%] | 30.1% | 0.0% | 0.0% | 0.0% |
| R3_any_approved | 245 | 35.5% [29.8%–41.7%] | 64.5% | 0.0% | 0.0% | 0.0% |
| R4_any_status | 23 | 0.0% [0.0%–14.3%] | 0.0% | 100.0% | 0.0% | 0.0% |
| unmatched | 376 | 0.0% [0.0%–1.0%] | 0.0% | 0.0% | 0.0% | 100.0% |

**Por candidatas en la ventana**

| Candidatas en la ventana | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| 0 | 376 | 0.0% [0.0%–1.0%] | 0.0% | 0.0% | 0.0% | 100.0% |
| 1 | 264 | 46.6% [40.7%–52.6%] | 44.7% | 8.7% | 0.0% | 0.0% |
| 2-5 | 343 | 58.6% [53.3%–63.7%] | 41.4% | 0.0% | 0.0% | 0.0% |
| >5 | 17 | 52.9% [31.0%–73.8%] | 47.1% | 0.0% | 0.0% | 0.0% |

**Por estilo del mensaje**

| Estilo del mensaje | n | Auto segura [IC 95%] | Handoff | Rechazo | No identificado | Sin match |
|---|---|---|---|---|---|---|
| amount_date | 326 | 54.0% [48.6%–59.3%] | 41.7% | 4.3% | 0.0% | 0.0% |
| amount_only | 157 | 52.9% [45.1%–60.5%] | 45.2% | 1.9% | 0.0% | 0.0% |
| date_only | 141 | 52.5% [44.3%–60.5%] | 43.3% | 4.3% | 0.0% | 0.0% |
| (sin conversación) | 376 | 0.0% [0.0%–1.0%] | 0.0% | 0.0% | 0.0% | 100.0% |

**Idioma (pares sobre los mismos casos, n=116; pt-BR = traducción del equipo):**

|  | es (dialecto del país) | pt-BR |
|---|---|---|
| Resolución automática segura | 52.6% [43.6%–61.4%] | 51.7% [42.7%–60.6%] |
| Handoff | 45.7% [36.9%–54.7%] | 45.7% [36.9%–54.7%] |
| No identificado | 0.0% [0.0%–3.2%] | 0.9% [0.2%–4.7%] |
| Turnos p50 | 2 | 2 |

Mismo resultado final en ambos idiomas: 99.1% [95.3%–99.8%].
Diferencias: `auto_resolved -> not_identified` (1).

## 5. Comparación con la operación humana histórica — **no comparable 1:1**

Mismas quejas de la muestra, desenlace registrado en el dataset. No es una comparación de igual a igual: el agente *abre* la disputa en el primer contacto; el histórico mide la *resolución completa* del caso por el back-office, que el replay no simula. Sirve para dimensionar el punto de partida, no para afirmar una mejora medida.

| Operación histórica (mismas quejas) | Valor | n |
|---|---|---|
| Estado: In Process 40.0%, Open 29.4%, Resolved 20.7%, Closed 4.7%, Escalated 3.8%, Rejected 1.4% |  | 1 000 |
| Incumplimiento de SLA | 17.1% [14.9%–19.6%] | 1 000 |
| Días de resolución p50 / p75 (solo con resolución registrada) | 15 / 23 | 243 |
| Horas hasta la primera respuesta p50 / p75 | 38.0 / 49.0 | 629 |
| Con compensación otorgada | 6.3% [5.0%–8.0%] | 1 000 |

| Resultado en la simulación | n | Hist. resuelta/cerrada | Hist. SLA incumplido | Hist. días p50 | Hist. compensación |
|---|---|---|---|---|---|
| Resolución automática segura (disputa abierta y verificada) | 333 | 24.3% | 19.5% | 16 | 6.6% |
| Derivado a humano (handoff) | 268 | 28.7% | 18.3% | 17 | 6.0% |
| Rechazada por política (D02–D05) | 23 | 26.1% | 4.3% | 12 | 8.7% |
| Sin transacción plausible (iría a un humano, no se conversa) | 376 | 23.9% | 14.9% | 15 | 6.1% |

En la simulación el agente responde en segundos (p50 64 ms de cómputo por caso) frente a una primera respuesta humana de 38.0 h (p50). Esa brecha es de **tiempo hasta la primera respuesta / apertura**, no de resolución, y es una simulación.

## 6. Modo sombra: decisión de la política vs desenlace histórico

Decisión de la política sobre el cargo emparejado (a la fecha de la queja, sin conversación) contra el estado histórico agrupado (resuelta = Resolved/Closed; abierta = Open/In Process). n=624 quejas emparejadas.

| Política \ Histórico | abierta | escalada | rechazada | resuelta | total |
|---|---|---|---|---|---|
| auto | 237 | 10 | 5 | 81 | 333 |
| handoff | 175 | 12 | 4 | 77 | 268 |
| rechazo | 15 | 2 | 0 | 6 | 23 |
| **total** | 427 | 24 | 9 | 164 | 624 |

Asociación: V de Cramér = 0.060 (permutación, p = 0.577).

| Par (política vs histórico) | n | % política | % histórico | Acuerdo obs. | Acuerdo por azar | κ Cohen | p (perm.) |
|---|---|---|---|---|---|---|---|
| handoff vs escalada o prioridad alta | 624 | 42.9% | 22.4% | 56.4% | 53.9% | 0.055 | 0.065 |
| auto vs resuelta | 624 | 53.4% | 26.3% | 46.3% | 48.4% | -0.040 | 0.898 |
| rechazo vs rechazada | 624 | 3.7% | 1.4% | 94.9% | 95.0% | -0.021 | 1.000 |
| H02 vs compensacion | 624 | 21.3% | 6.4% | 74.5% | 75.0% | -0.020 | 0.799 |
| H03 vs prioridad critica | 624 | 0.2% | 5.6% | 94.2% | 94.2% | -0.003 | 1.000 |

**Interpretación:** el acuerdo es **indistinguible del azar** (κ ≈ 0 en todos los pares y V de Cramér baja). El desenlace histórico del dataset sintético no depende de los atributos que usa la política (estado del cliente, monto, fraud_score, reclamante recurrente), igual que otros campos del dataset son uniformes (ver `reports/EDA_findings.md`, limitación 9). Esto **no valida ni invalida** la política: dice que el histórico no sirve como etiqueta de "decisión correcta" y que cualquier afirmación de "el agente coincide con los analistas" sería falsa con estos datos.

### Sensibilidad a la regla de emparejamiento

Decisión de la política con la regla principal vs con "la más reciente de cualquier estado" (misma transacción en 504 de 624 casos):

| Regla que decide | Regla principal | Alternativa |
|---|---|---|
| D02_declined_not_charged | 11 | 27 |
| D03_already_reversed | 5 | 11 |
| D04_pending | 7 | 11 |
| H01_customer_not_active | 92 | 90 |
| H02_high_amount | 106 | 137 |
| H03_fraud_signal | 1 | 1 |
| H04_repeat_complainer | 69 | 55 |
| ninguna (automatizable) | 333 | 292 |

H04 a la fecha de la queja vs con todas las quejas (semántica de producción): difieren en 18 casos (18 serían H04 solo por quejas **posteriores**).

## 7. Sensibilidad de umbrales H02 / H03 (solo política, sobre los cargos emparejados)

Cuánto cambia la carga de analistas si se mueven los umbrales. `H02 ×` escala los montos altos por moneda de `config/policy.yaml`; `H03` es el `fraud_score` mínimo (hoy 30, ver `reports/fraud_threshold.md`).

| H03 fraud_score ≥ | H02 monto | Handoff | Automatizable | n |
|---|---|---|---|---|
| 20 | ×0.5 | 59.5% | 36.9% | 624 |
| 20 | ×1 | 56.6% | 39.7% | 624 |
| 20 | ×2 | 51.9% | 44.4% | 624 |
| 30 | ×0.5 | 46.3% | 50.0% | 624 |
| 30 | ×1 | 42.9% | 53.4% | 624 |
| 30 | ×2 | 36.5% | 59.8% | 624 |
| 40 | ×0.5 | 46.3% | 50.0% | 624 |
| 40 | ×1 | 42.9% | 53.4% | 624 |
| 40 | ×2 | 36.5% | 59.8% | 624 |
| 50 | ×0.5 | 46.3% | 50.0% | 624 |
| 50 | ×1 | 42.9% | 53.4% | 624 |
| 50 | ×2 | 36.5% | 59.8% | 624 |

## 8. PROYECCIÓN de impacto (no medido; supuestos explícitos)

> **PROYECCIÓN**, no resultado: combina la tasa simulada con volúmenes y duraciones del dataset sintético.

- **Volumen:** 8 169 quejas de estas dos subcategorías en los últimos 365 días del dataset.
- **Tasa automatizable:** resolución automática segura de la simulación, 33.3% [30.4%–36.3%] (sobre el total, incluye sin match).
- **Tiempo de asesor por queja:** duración de las llamadas con `reason_category = Queja` (n=117 021): p25 343 s, p50 431 s, p75 522 s. 63.0% de esas llamadas requieren seguimiento; el escenario alto supone un contacto adicional de igual duración en esa proporción.
- **Supuestos:** una queja automatizada evita al menos un contacto de asesor; no se cuenta el trabajo de back-office (la disputa sigue requiriendo resolución), ni el costo del canal automático, ni efectos en satisfacción. Las quejas no se pueden unir a las llamadas (sin `origin_interaction_id`), así que "un contacto por queja" es un supuesto.

| Escenario | Supuesto | Horas de asesor / año |
|---|---|---|
| Bajo | IC inferior de la tasa × p25 de duración × 1 contacto | 237 |
| Central | tasa puntual × mediana × 1 contacto | 326 |
| Alto | IC superior × p75 × (1 + 63% seguimiento) | 700 |

Rango proyectado: **237–700 horas de asesor por año** para el volumen del dataset. No es un ahorro medido.

## 9. Limitaciones

- **La transacción disputada es inferida.** No hay etiqueta; el agente se mide contra la regla de emparejamiento. Un cliente real podría estar reclamando otro cargo (o un cargo fuera de la ventana).
- **Cliente simulado cooperativo.** Siempre recuerda el monto/fecha exactos, reconoce su cargo entre las opciones y confirma. Los clientes reales se equivocan, cambian de tema o abandonan: la tasa real sería menor.
- **Mensajes generados por el equipo** con plantillas por dialecto; no hay texto real de clientes (las descripciones del dataset son plantillas y las transcripciones no dependen del motivo). La variante pt-BR es traducción del equipo.
- **Estado actual, no histórico:** `transaction_status` y `customer_status` son los de la última entrega. Un cargo hoy *Reversed* pudo estar *Approved* cuando se creó la queja (y quizás se reversó *por* la queja), y un cliente hoy inactivo (H01) pudo estar activo. El replay no puede reconstruir esos estados.
- **D05 no se ejerce:** con ventana de emparejamiento de 60 días, ningún cargo emparejado supera los 120 días del plazo. Evaluar a la fecha de la queja sí evita que las quejas de 2023–2025 se rechacen todas por antigüedad, que es lo que pasaría con el `as_of` fijo del YAML.
- **Datos sintéticos:** distribuciones uniformes e independencia entre campos (monto reclamado, producto afectado, desenlace). El modo sombra lo confirma; ninguna conclusión de acuerdo con el histórico es transferible a un banco real.
- **Latencia** medida en un solo proceso local con reglas y plantillas: no incluye red, LLM ni concurrencia.

## 10. Reproducibilidad

|  |  |
|---|---|
| Comando | `python -m bankagent.evals.replay --db serving_full.duckdb --n 1000 --seed 7 --history-db bank.duckdb` |
| Seed | 7 |
| Commit | `09e2d0f` |
| Política | `2026-09-29.1` (as_of del YAML 2026-06-17; el replay usa la fecha de cada queja) |
| Base | `serving_full.duckdb` · corrida del pipeline `20260928T220955-c6fe82` |
| Huella de la entrega | customers=`c5fcfddc9ed220fa`, products=`151a201d660a17b5`, transactions=`f8547ae41edd4ab7`, complaints=`3d3ddc541abc6c6b` |
| Historial | `bank.duckdb` (tablas raw del EDA, solo lectura) |
| Parámetros | ventana 60 días, tolerancia de monto ±10%, tope 6 turnos, pt-BR 20% |
| Duración de la corrida | 117.2 s |

Los números de este reporte y `reports/replay_results.json` salen del mismo comando. El detalle por caso (con IDs del dataset) queda en `data/replay/cases.jsonl`, fuera del repositorio. Con el mismo seed, la misma base y el mismo commit, todo se reproduce salvo las latencias.
