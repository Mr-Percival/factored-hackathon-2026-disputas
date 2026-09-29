# Router de intención aprendido vs. RuleRouter

> Generado por `scripts/train_intent.py` — no editar a mano. Decisión y justificación: [ADR 0009](../docs/adr/0009-router-aprendido.md). Corpus, guía y anotaciones: [`corpus/intent/`](../corpus/intent/).

- **Aprendido lite (char) — se despliega:** `char2-5-tfidf` + regresión logística (C=10.0, clases balanceadas), temperatura T=0.48, umbral de abstención τ=0.69 (máxima cobertura con acción equivocada ≤ 1% en validación). Artefactos `models/intent_router_lite/` (0.2 MB).
- **Aprendido full (char+MiniLM) — offline:** `char2-5-tfidf+qdrant/paraphrase-multilingual-MiniLM-L12-v2-onnx-Q@faf4aa42` + regresión logística (C=10.0, clases balanceadas), temperatura T=0.58, umbral de abstención τ=0.74 (máxima cobertura con acción equivocada ≤ 1% en validación). Artefactos `models/intent_router_full/` (0.2 MB).
- Corpus de train sha256 `4cd70e1c063d07e7…`; test congelado en `corpus/intent/MANIFEST.json` (2026-09-29T01:25:19).

## Resumen

| split | métrica | RuleRouter (línea base) | Aprendido lite (char) — se despliega | Aprendido full (char+MiniLM) — offline |
|---|---|---|---|---|
| **test (autores C y G)** | n=306 (152 familias) |  |  |  |
|  | macro-F1, 9 intenciones (IC 95%) | 0.548 [0.473, 0.604] | 0.877 [0.832, 0.913] | 0.924 [0.876, 0.957] |
|  | Δ macro-F1 vs. reglas (IC 95%) | — | +0.330 [0.257, 0.409] | +0.376 [0.300, 0.456] |
|  | macro-F1 por ruta del grafo | 0.571 | 0.856 | 0.920 |
|  | mensajes con acción equivocada | 18.6% (57) | 1.6% (5) | 1.6% (5) |
|  | handoff pedido → se inició disputa | 33 | 3 | 2 |
|  | costo esperado por mensaje (IC 95%) | 0.673 [0.544, 0.820] | 0.105 [0.060, 0.161] | 0.080 [0.034, 0.138] |
|  | cobertura (sin aclarar por baja confianza) | 64.7% | 89.5% | 94.4% |
|  | 5 semillas (85% de familias): macro-F1 | — | 0.846 ± 0.011 | 0.902 ± 0.013 |
| **test de estilo no visto (autor D)** | n=175 (69 familias) |  |  |  |
|  | macro-F1, 9 intenciones (IC 95%) | 0.719 [0.631, 0.783] | 0.869 [0.814, 0.910] | 0.895 [0.838, 0.939] |
|  | Δ macro-F1 vs. reglas (IC 95%) | — | +0.151 [0.078, 0.236] | +0.177 [0.101, 0.272] |
|  | macro-F1 por ruta del grafo | 0.712 | 0.842 | 0.867 |
|  | mensajes con acción equivocada | 1.1% (2) | 0.0% (0) | 0.0% (0) |
|  | handoff pedido → se inició disputa | 1 | 0 | 0 |
|  | costo esperado por mensaje (IC 95%) | 0.211 [0.147, 0.283] | 0.086 [0.056, 0.119] | 0.074 [0.040, 0.114] |
|  | cobertura (sin aclarar por baja confianza) | 58.9% | 88.6% | 93.1% |
|  | 5 semillas (85% de familias): macro-F1 | — | 0.861 ± 0.011 | 0.888 ± 0.007 |
| **CPU, 1 hilo** | latencia de clasificación p50 / p95 (HybridRouter = esto + reglas) | 0.53 / 0.69 ms | 0.18 / 0.27 ms | 14.80 / 23.04 ms |
|  | en disco | 0 MB | 0.2 MB + 0 MB preentrenado | 0.2 MB + 252.1 MB preentrenado |

- Las 9 etiquetas son las intenciones de usuario que el grafo ya maneja (#54); RuleRouter las cubre todas, así que la comparación es directa. RuleRouter se evalúa como lo usa el grafo: confianza < 0.6 → aclarar (`unknown`).
- **Acción equivocada** = el grafo propone una disputa o un bloqueo cuando la ruta correcta era otra (todas las acciones piden confirmación, así que es el error más caro que el router puede provocar).
- **Costo** (`intent_model.error_cost`): aclarar 0.5 · handoff innecesario 1 · handoff a la cola equivocada 0.5 (1 si era toma de cuenta) · consultar estado sin pedirlo 1 · cerrar con un pedido abierto 1.5 · proponer disputa/bloqueo indebido 2, o 3 si el cliente pedía un humano, reportaba robo de cuenta o retiraba un reclamo.
- IC 95% por bootstrap de **familias** de paráfrasis (2000 réplicas): las paráfrasis de una misma idea no son independientes.

## Datos y etiquetas

| intención | train (n=864) | test (n=306) | test_style (n=175) |
|---|---|---|---|
| dispute_charge | 229 | 67 | 46 |
| block_card | 95 | 33 | 23 |
| account_takeover | 62 | 23 | 15 |
| human_request | 69 | 18 | 16 |
| dispute_status | 57 | 38 | 0 |
| cancel_dispute | 52 | 33 | 0 |
| out_of_scope | 186 | 57 | 51 |
| closing | 47 | 17 | 11 |
| unknown | 67 | 20 | 13 |

| dialecto | train | test | test_style |
|---|---|---|---|
| es-MX | 234 | 72 | 43 |
| es-CO | 197 | 58 | 42 |
| es-AR | 176 | 64 | 33 |
| pt-BR | 216 | 82 | 40 |
| mix | 41 | 30 | 17 |

- **Procedencia:** enunciados escritos por el equipo con asistentes de IA, un autor por sesión aislada que solo leyó la [guía de etiquetado](../corpus/intent/GUIA_ETIQUETADO.md) (ni las reglas ni otros archivos del corpus). Split **por autor, fijado antes de escribir**: A, B, E, F → train; C, G → test; D → test de estilo no visto (voz a texto, telegráfico, formal). F y G se sumaron en la v2 de la guía para las intenciones nuevas de #54 (`dispute_status`, `cancel_dispute`); los archivos anteriores no se tocaron y una revisión completa no encontró enunciados viejos que cambiaran de etiqueta (`review/schema_v2_relabel.jsonl` vacío). No hay texto de clientes ni del dataset del organizador (ADR 0003).
- **Validez de etiquetas:** anotaciones ciegas (solo el texto + la guía) comparadas con la etiqueta del autor antes de adjudicar; los desacuerdos se resolvieron en `review/adjudication.jsonl` (o se descartaron por ambiguos). El acuerdo es muy alto: el corpus es *limpio* (ver Limitaciones).

| split · anotador | n | acuerdo | κ de Cohen | desacuerdos | reetiquetados | descartados |
|---|---|---|---|---|---|---|
| train · second | 150 | 98.7% | 0.984 | 2 | 1 | 1 |
| test · second | 233 | 100.0% | 1.000 | 0 | 0 | 0 |
| test_style · second | 185 | 100.0% | 1.000 | 0 | 0 | 0 |
| test · third | 95 | 100.0% | 1.000 | 0 | 0 | 0 |
| test_style · third | 65 | 98.5% | 0.981 | 1 | 0 | 1 |
| train · fourth | 40 | 100.0% | 1.000 | 0 | 0 | 0 |
| test · fourth | 110 | 100.0% | 1.000 | 0 | 0 | 0 |

- **Fuga:** familias de paráfrasis y autores nunca cruzan splits; el vocabulario de n-gramas y la temperatura se ajustan dentro de cada fold; el test no participa de ninguna selección; casi-duplicados de train (Jaccard de trigramas ≥ 0.8, en general saludos o cierres cortos) se sacan del test: 37 en test, 9 en estilo. El script aborta si los hashes congelados del test cambian.

## Selección del componente (solo validación cruzada por autor sobre train)

Cada fold entrena con todos los autores de train menos uno y valida con el que quedó afuera (un autor que el modelo nunca vio, como en el test). Encoder, C, temperatura y umbral salen de acá; el test se evalúa una sola vez al final. Latencia: un mensaje a la vez tras calentar, 1 hilo.

| candidato | macro-F1 | C | T | ECE cruda → calibrada | τ | cobertura | acción equivocada | costo/msg | p50 / p95 ms | MB preentrenado |
|---|---|---|---|---|---|---|---|---|---|---|
| `char` ← lite | 0.875 | 10.0 | 0.48 | 0.192 → 0.019 | 0.69 | 84.4% | 0.9% | 0.121 | 0.18 / 0.27 | 0 |
| `m2v` | 0.806 | 30.0 | 0.89 | 0.029 → 0.021 | 0.82 | 63.7% | 0.9% | 0.209 | 0.18 / 0.25 | 531.0 |
| `minilm` | 0.895 | 30.0 | 0.80 | 0.046 → 0.010 | 0.82 | 79.3% | 0.9% | 0.135 | 13.77 / 20.41 | 252.1 |
| `e5` | 0.857 | 30.0 | 0.58 | 0.136 → 0.018 | 0.81 | 74.8% | 0.9% | 0.156 | 9.99 / 15.58 | 135.4 |
| `char+m2v` | 0.876 | 30.0 | 0.72 | 0.059 → 0.028 | 0.80 | 78.5% | 0.9% | 0.133 | 0.38 / 0.49 | 531.0 |
| `char+minilm` ← full | 0.924 | 10.0 | 0.58 | 0.105 → 0.019 | 0.74 | 89.4% | 0.9% | 0.089 | 14.80 / 23.04 | 252.1 |
| RuleRouter | — |  |  |  |  |  | 8.3% | 0.411 | 0.53 / 0.69 | 0 |

`char` = TF-IDF de n-gramas de caracteres 2–5 aprendido del corpus; `m2v` = model2vec potion-multilingual-128M; `minilm` = paraphrase-multilingual-MiniLM-L12-v2 (ONNX int8); `e5` = multilingual-e5-small (ONNX int8). Regla fijada antes de mirar el test: **full** = mayor macro-F1 en validación (si otro queda a menos de 0.01, el más liviano). **lite** = `char`, el único que entra en el deploy gratuito (512 MB de RAM, 0.1 CPU) sin onnxruntime ni un modelo de 250 MB. Umbral τ: máxima cobertura con acción equivocada ≤ 1% en validación.

![Cobertura vs acción equivocada](figures/intent_coverage.png)

## Resultados — test (autores C y G)

|  | Aprendido lite (char) — se despliega | Aprendido full (char+MiniLM) — offline |
|---|---|---|
| ECE (10 bins) | 0.036 | 0.023 |
| macro-F1 sin abstención | 0.905 | 0.951 |
| acción equivocada sin abstención | 4.6% | 3.6% |

### Por intención (precisión / recall / F1)

| intención | soporte | rules P/R/F1 | lite P/R/F1 | full P/R/F1 |
|---|---|---|---|---|
| dispute_charge | 67 | 0.38 / 0.49 / 0.43 | 0.95 / 0.94 / 0.95 | 0.97 / 0.96 / 0.96 |
| block_card | 33 | 0.86 / 0.73 / 0.79 | 0.94 / 0.94 / 0.94 | 0.92 / 1.00 / 0.96 |
| account_takeover | 23 | 0.67 / 0.26 / 0.38 | 1.00 / 0.87 / 0.93 | 1.00 / 0.87 / 0.93 |
| human_request | 18 | 0.68 / 0.72 / 0.70 | 1.00 / 0.94 / 0.97 | 0.94 / 0.94 / 0.94 |
| dispute_status | 38 | 0.92 / 0.29 / 0.44 | 1.00 / 0.66 / 0.79 | 1.00 / 0.87 / 0.93 |
| cancel_dispute | 33 | 0.93 / 0.42 / 0.58 | 0.96 / 0.79 / 0.87 | 0.97 / 0.91 / 0.94 |
| out_of_scope | 57 | 0.92 / 0.21 / 0.34 | 0.96 / 0.89 / 0.93 | 0.96 / 0.89 / 0.93 |
| closing | 17 | 1.00 / 0.94 / 0.97 | 1.00 / 0.94 / 0.97 | 1.00 / 0.94 / 0.97 |
| unknown | 20 | 0.18 / 0.95 / 0.30 | 0.39 / 0.95 / 0.55 | 0.61 / 1.00 / 0.75 |

### Confusión por ruta del grafo

RuleRouter (línea base):

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 33 | 0 | 0 | 6 | 0 | 28 |
| bloqueo | 0 | 24 | 0 | 3 | 0 | 6 |
| estado | 19 | 0 | 11 | 0 | 0 | 8 |
| handoff | 33 | 3 | 1 | 47 | 0 | 47 |
| cierre | 1 | 0 | 0 | 0 | 16 | 0 |
| aclarar | 0 | 1 | 0 | 0 | 0 | 19 |

Aprendido lite (char) — se despliega:

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 63 | 0 | 0 | 0 | 0 | 4 |
| bloqueo | 0 | 31 | 0 | 0 | 0 | 2 |
| estado | 0 | 0 | 25 | 0 | 0 | 13 |
| handoff | 3 | 2 | 0 | 116 | 0 | 10 |
| cierre | 0 | 0 | 0 | 0 | 16 | 1 |
| aclarar | 0 | 0 | 0 | 1 | 0 | 19 |

Aprendido full (char+MiniLM) — offline:

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 64 | 0 | 0 | 1 | 0 | 2 |
| bloqueo | 0 | 33 | 0 | 0 | 0 | 0 |
| estado | 0 | 0 | 33 | 1 | 0 | 4 |
| handoff | 2 | 3 | 0 | 120 | 0 | 6 |
| cierre | 0 | 0 | 0 | 0 | 16 | 1 |
| aclarar | 0 | 0 | 0 | 0 | 0 | 20 |

<details><summary>Matriz de confusión de 9 intenciones (lite)</summary>

| verdad \ predicción | dispute charge | block card | account takeover | human request | dispute status | cancel dispute | out of scope | closing | unknown |
|---|---|---|---|---|---|---|---|---|---|
| dispute charge | 63 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 4 |
| block card | 0 | 31 | 0 | 0 | 0 | 0 | 0 | 0 | 2 |
| account takeover | 1 | 0 | 20 | 0 | 0 | 0 | 0 | 0 | 2 |
| human request | 0 | 0 | 0 | 17 | 0 | 0 | 1 | 0 | 0 |
| dispute status | 0 | 0 | 0 | 0 | 25 | 0 | 0 | 0 | 13 |
| cancel dispute | 1 | 0 | 0 | 0 | 0 | 26 | 0 | 0 | 6 |
| out of scope | 1 | 2 | 0 | 0 | 0 | 1 | 51 | 0 | 2 |
| closing | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 16 | 1 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 19 |

</details>

### Exactitud por autor, dialecto, estilo y negativos difíciles

| corte | grupo | n | rules | lite | full |
|---|---|---|---|---|---|
| autor | C | 203 | 54.7% | 92.1% | 94.1% |
| autor | G | 103 | 35.9% | 78.6% | 90.3% |
| dialecto | es-AR | 64 | 45.3% | 87.5% | 93.8% |
| dialecto | es-CO | 58 | 39.7% | 82.8% | 87.9% |
| dialecto | es-MX | 72 | 47.2% | 88.9% | 91.7% |
| dialecto | mix | 30 | 73.3% | 96.7% | 100.0% |
| dialecto | pt-BR | 82 | 48.8% | 86.6% | 93.9% |
| estilo | chat | 207 | 41.1% | 85.5% | 91.8% |
| estilo | emoji | 7 | 42.9% | 71.4% | 100.0% |
| estilo | formal | 11 | 63.6% | 81.8% | 90.9% |
| estilo | largo | 5 | 60.0% | 80.0% | 80.0% |
| estilo | portunol | 16 | 81.2% | 100.0% | 100.0% |
| estilo | terse | 25 | 80.0% | 96.0% | 96.0% |
| estilo | typos | 24 | 41.7% | 100.0% | 95.8% |
| negativo difícil | False | 230 | 52.6% | 88.3% | 94.8% |
| negativo difícil | True | 76 | 35.5% | 85.5% | 86.8% |

### Errores

**lite**: 38 errores (27 también de reglas). Pares más frecuentes: dispute_status → unknown (13), cancel_dispute → unknown (6), dispute_charge → unknown (4), block_card → unknown (2), account_takeover → unknown (2), out_of_scope → unknown (2).

**full**: 22 errores (15 también de reglas). Pares más frecuentes: dispute_status → unknown (4), account_takeover → unknown (3), out_of_scope → block_card (3), dispute_charge → unknown (2), cancel_dispute → unknown (2), dispute_charge → human_request (1).

Errores más confiados de **lite** (los más peligrosos: la abstención no los frena):

| id | dialecto | texto | verdad | lite (p) | reglas |
|---|---|---|---|---|---|
| C-0186 | pt-BR | o app diz que meu cartão tá bloqueado, quero liberar pra usar | out_of_scope | block_card (0.9819999933242798) | block_card |
| C-0219 | pt-BR | quanto tá o jogo do Flamengo? | unknown | out_of_scope (0.9760000109672546) | unknown |
| C-0202 | es-CO | Nada más, que tenga buen día. | closing | unknown (0.968999981880188) | closing |
| G-0086 | pt-BR | quero cancelar o seguro do cartão | out_of_scope | block_card (0.9629999995231628) | out_of_scope |
| C-0169 | es-AR | qué pasa si desconozco una compra, me devuelven la plata al toque? pregunto nomás | out_of_scope | dispute_charge (0.9419999718666077) | dispute_charge |
| C-0135 | es-AR | cuánto tengo que escribir para que me atienda una persona?? | human_request | out_of_scope (0.8970000147819519) | unknown |
| G-0085 | es-AR | quiero cancelar la transferencia que hice recién, me equivoqué de CBU | out_of_scope | cancel_dispute (0.8640000224113464) | out_of_scope |
| C-0107 | es-CO | alguien entró a mi app y compró cosas con mi tarjeta, no reconozco ninguno de esos cargos | account_takeover | dispute_charge (0.8299999833106995) | account_takeover |
| G-0063 | es-AR | ey, el cobro de Netflix que desconocí era de la cuenta que comparto con mi hermana, olvidate del reclamo | cancel_dispute | dispute_charge (0.7580000162124634) | dispute_charge |
| G-0036 | pt-BR | abri uma reclamação do débito duplicado no mercado e até agora nada, como tá isso? | dispute_status | unknown (0.6880000233650208) | unknown |
| G-0026 | es-AR | ¿Me confirmás que recibieron el reclamo que hice ayer por el cobro duplicado? | dispute_status | unknown (0.6830000281333923) | dispute_charge |
| G-0033 | es-CO | hola 😊 queria saber si ya abonaron lo de mi disputa | dispute_status | unknown (0.6759999990463257) | dispute_charge |

<details><summary>lite acierta y reglas fallan (131) · reglas aciertan y lite falla (11)</summary>

| id | texto | verdad | reglas | lite |
|---|---|---|---|---|
| C-0006 | fui cobrado duas vezes no posto Ipiranga, R$ 230 cada uma | dispute_charge | unknown | dispute_charge |
| C-0007 | el cajero de la 72 con septima no me dio la plata pero si me descontaron 400 mil | dispute_charge | unknown | dispute_charge |
| C-0008 | saque del cajero, no salio el dinero y en la app ya me aparece el retiro de 3000 | dispute_charge | unknown | dispute_charge |
| C-0009 | o caixa eletrônico não soltou as notas e o saque de R$ 500 foi debitado mesmo assim | dispute_charge | unknown | dispute_charge |
| C-0012 | me di de baja del gimnasio y me lo siguen debitando, ya van 2 meses 😡 | dispute_charge | unknown | dispute_charge |
| C-0013 | pagué 38.500 en el restaurante y en el resumen figura 85.300, alguien tipeó mal y quiero que lo corr | dispute_charge | unknown | dispute_charge |
| C-0014 | en Crepes & Waffles pague 96 mil y me cargaron 196 mil, eso no es lo que firmé | dispute_charge | unknown | dispute_charge |
| C-0015 | o valor que caiu na fatura da Drogasil tá errado, era R$ 74 e veio R$ 740 | dispute_charge | unknown | dispute_charge |
| C-0018 | comprei um celular no site da Casas Bahia, não chegou nada e já foi cobrado | dispute_charge | unknown | dispute_charge |
| C-0020 | hola, apareceu un débito de 120 dólares de la aerolínea Azul, yo no compré nada | dispute_charge | unknown | dispute_charge |
| C-0021 | me robaron la billetera y ya hay una compra en un Oxxo que no hice | dispute_charge | unknown | dispute_charge |
| C-0022 | me robaron la tarjeta en el Transmilenio y ya aparece un cargo de 250 mil en el Éxito | dispute_charge | unknown | dispute_charge |
| C-0017 | pedí una licuadora por internet en Falabella, el pedido nunca llegó pero el cargo sí salió en el ext | dispute_charge | dispute_charge | unknown |
| C-0082 | necesito hacer block de mi card, la perdí en el Uber | block_card | block_card | unknown |
| C-0105 | entraron a mi banca en línea y hicieron 3 transferencias que no reconozco | account_takeover | account_takeover | unknown |
| C-0106 | hackearam minha conta e fizeram um pix de R$ 2.000 que eu não reconheço | account_takeover | account_takeover | unknown |
| C-0107 | alguien entró a mi app y compró cosas con mi tarjeta, no reconozco ninguno de esos cargos | account_takeover | account_takeover | dispute_charge |
| C-0202 | Nada más, que tenga buen día. | closing | closing | unknown |
| C-0219 | quanto tá o jogo do Flamengo? | unknown | unknown | out_of_scope |
| G-0009 | Buenas tardes, quisiera consultar el estado de la disputa que radiqué el lunes por un cobro de Rappi | dispute_status | dispute_status | unknown |
| G-0060 | ya me devolvieron la plata directamente, anulen el reclamo porfa | cancel_dispute | cancel_dispute | unknown |
| G-0085 | quiero cancelar la transferencia que hice recién, me equivoqué de CBU | out_of_scope | out_of_scope | cancel_dispute |
| G-0086 | quero cancelar o seguro do cartão | out_of_scope | out_of_scope | block_card |

</details>

## Resultados — test de estilo no visto (autor D)

|  | Aprendido lite (char) — se despliega | Aprendido full (char+MiniLM) — offline |
|---|---|---|
| ECE (10 bins) | 0.033 | 0.037 |
| macro-F1 sin abstención | 0.937 | 0.936 |
| acción equivocada sin abstención | 1.7% | 0.6% |

### Por intención (precisión / recall / F1)

| intención | soporte | rules P/R/F1 | lite P/R/F1 | full P/R/F1 |
|---|---|---|---|---|
| dispute_charge | 46 | 0.97 / 0.72 / 0.82 | 1.00 / 0.72 / 0.84 | 1.00 / 0.76 / 0.86 |
| block_card | 23 | 0.94 / 0.74 / 0.83 | 1.00 / 0.96 / 0.98 | 1.00 / 0.96 / 0.98 |
| account_takeover | 15 | 1.00 / 0.53 / 0.70 | 1.00 / 0.87 / 0.93 | 1.00 / 0.93 / 0.97 |
| human_request | 16 | 1.00 / 0.81 / 0.90 | 1.00 / 0.94 / 0.97 | 1.00 / 1.00 / 1.00 |
| dispute_status | 0 | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.00 |
| cancel_dispute | 0 | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.00 | 0.00 / 0.00 / 0.00 |
| out_of_scope | 51 | 1.00 / 0.35 / 0.52 | 0.90 / 0.88 / 0.89 | 0.88 / 0.90 / 0.89 |
| closing | 11 | 0.92 / 1.00 / 0.96 | 1.00 / 0.91 / 0.95 | 1.00 / 0.91 / 0.95 |
| unknown | 13 | 0.18 / 1.00 / 0.31 | 0.38 / 0.92 / 0.53 | 0.46 / 0.92 / 0.62 |

### Confusión por ruta del grafo

RuleRouter (línea base):

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 33 | 0 | 0 | 0 | 0 | 13 |
| bloqueo | 0 | 17 | 0 | 0 | 0 | 6 |
| estado | 0 | 0 | 0 | 0 | 0 | 0 |
| handoff | 1 | 1 | 0 | 39 | 1 | 40 |
| cierre | 0 | 0 | 0 | 0 | 11 | 0 |
| aclarar | 0 | 0 | 0 | 0 | 0 | 13 |

Aprendido lite (char) — se despliega:

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 33 | 0 | 0 | 3 | 0 | 10 |
| bloqueo | 0 | 22 | 0 | 0 | 0 | 1 |
| estado | 0 | 0 | 0 | 0 | 0 | 0 |
| handoff | 0 | 0 | 0 | 73 | 0 | 9 |
| cierre | 0 | 0 | 0 | 1 | 10 | 0 |
| aclarar | 0 | 0 | 0 | 1 | 0 | 12 |

Aprendido full (char+MiniLM) — offline:

| verdad \ predicción | disputa | bloqueo | estado | handoff | cierre | aclarar |
|---|---|---|---|---|---|---|
| disputa | 35 | 0 | 0 | 5 | 0 | 6 |
| bloqueo | 0 | 22 | 0 | 0 | 0 | 1 |
| estado | 0 | 0 | 0 | 0 | 0 | 0 |
| handoff | 0 | 0 | 0 | 76 | 0 | 6 |
| cierre | 0 | 0 | 0 | 0 | 10 | 1 |
| aclarar | 0 | 0 | 0 | 1 | 0 | 12 |

<details><summary>Matriz de confusión de 9 intenciones (lite)</summary>

| verdad \ predicción | dispute charge | block card | account takeover | human request | dispute status | cancel dispute | out of scope | closing | unknown |
|---|---|---|---|---|---|---|---|---|---|
| dispute charge | 33 | 0 | 0 | 0 | 0 | 0 | 3 | 0 | 10 |
| block card | 0 | 22 | 0 | 0 | 0 | 0 | 0 | 0 | 1 |
| account takeover | 0 | 0 | 13 | 0 | 0 | 0 | 0 | 0 | 2 |
| human request | 0 | 0 | 0 | 15 | 0 | 0 | 0 | 0 | 1 |
| dispute status | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| cancel dispute | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 0 |
| out of scope | 0 | 0 | 0 | 0 | 0 | 0 | 45 | 0 | 6 |
| closing | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 10 | 0 |
| unknown | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 12 |

</details>

### Exactitud por autor, dialecto, estilo y negativos difíciles

| corte | grupo | n | rules | lite | full |
|---|---|---|---|---|---|
| autor | D | 175 | 64.6% | 85.7% | 88.6% |
| dialecto | es-AR | 33 | 57.6% | 90.9% | 93.9% |
| dialecto | es-CO | 42 | 71.4% | 83.3% | 83.3% |
| dialecto | es-MX | 43 | 60.5% | 86.0% | 90.7% |
| dialecto | mix | 17 | 100.0% | 82.4% | 94.1% |
| dialecto | pt-BR | 40 | 52.5% | 85.0% | 85.0% |
| estilo | formal | 47 | 61.7% | 76.6% | 85.1% |
| estilo | terse | 59 | 61.0% | 86.4% | 83.1% |
| estilo | voz | 69 | 69.6% | 91.3% | 95.7% |
| negativo difícil | False | 154 | 70.1% | 83.8% | 87.0% |
| negativo difícil | True | 21 | 23.8% | 100.0% | 100.0% |

### Errores

**lite**: 25 errores (11 también de reglas). Pares más frecuentes: dispute_charge → unknown (10), out_of_scope → unknown (6), dispute_charge → out_of_scope (3), account_takeover → unknown (2), block_card → unknown (1), human_request → unknown (1).

**full**: 20 errores (9 también de reglas). Pares más frecuentes: dispute_charge → unknown (6), dispute_charge → out_of_scope (5), out_of_scope → unknown (5), block_card → unknown (1), account_takeover → unknown (1), closing → unknown (1).

Errores más confiados de **lite** (los más peligrosos: la abstención no los frena):

| id | dialecto | texto | verdad | lite (p) | reglas |
|---|---|---|---|---|---|
| D-0164 | es-MX | cuál es la capital de Perú | unknown | out_of_scope (0.9980000257492065) | unknown |
| D-0143 | es-MX | Agradezco su atención; no requiero nada más por el momento. Quedo atento. | closing | out_of_scope (0.9070000052452087) | closing |
| D-0032 | es-CO | monto distinto al pagado | dispute_charge | out_of_scope (0.902999997138977) | unknown |
| D-0134 | mix | hola eh queria saber si tengo seguro de vida no cartão ou como contrato um | out_of_scope | unknown (0.8849999904632568) | out_of_scope |
| D-0009 | es-AR | Estimados: por la presente informo que el cajero automático no me entregó el efectivo solicitado y, sin embarg | dispute_charge | out_of_scope (0.7250000238418579) | unknown |
| D-0030 | es-MX | Solicito respetuosamente la aclaración de dos cargos idénticos por mil doscientos pesos efectuados en el mismo | dispute_charge | out_of_scope (0.7070000171661377) | dispute_charge |
| D-0003 | es-MX | Estimados, por medio de la presente manifiesto que no reconozco el cargo por trescientos cincuenta pesos aplic | dispute_charge | unknown (0.6779999732971191) | dispute_charge |
| D-0024 | es-AR | Estimados, me dirijo a ustedes para impugnar un consumo por nueve mil pesos correspondiente a un pedido cancel | dispute_charge | unknown (0.6779999732971191) | unknown |
| D-0018 | es-MX | A quien corresponda: solicito la cancelación de un cargo recurrente de ciento ochenta pesos por un servicio qu | dispute_charge | unknown (0.6269999742507935) | dispute_charge |
| D-0080 | pt-BR | caí num golpe de phishing | account_takeover | unknown (0.6240000128746033) | unknown |
| D-0166 | es-CO | envío de tarjeta | out_of_scope | unknown (0.6240000128746033) | unknown |
| D-0039 | pt-BR | Prezados, solicito a revisão de uma transação de cento e cinquenta reais cujo valor diverge do comprovante que | dispute_charge | unknown (0.6159999966621399) | unknown |

<details><summary>lite acierta y reglas fallan (51) · reglas aciertan y lite falla (14)</summary>

| id | texto | verdad | reglas | lite |
|---|---|---|---|---|
| D-0007 | mirá che tipo estaba en el cajero de la calle corrientes no perdón en el de avenida cabildo y puse l | dispute_charge | unknown | dispute_charge |
| D-0008 | cajero no dio plata | dispute_charge | unknown | dispute_charge |
| D-0017 | me siguen cobrando | dispute_charge | unknown | dispute_charge |
| D-0029 | dos cargos iguales | dispute_charge | unknown | dispute_charge |
| D-0034 | mirá yo no sé qué es esto pero me aparece un débito de una app de juegos que jamás instalé por cuatr | dispute_charge | unknown | dispute_charge |
| D-0038 | valor cobrado errado | dispute_charge | unknown | dispute_charge |
| D-0042 | me robaron la tarjeta y ya vi que con ella hicieron una compra de dos mil pesos en gasolinera que yo | dispute_charge | unknown | dispute_charge |
| D-0053 | Cordial saludo, solicito el bloqueo de mi tarjeta crédito por hurto del bolso. | block_card | unknown | block_card |
| D-0060 | meu filho mexeu na minha carteira e acho que o cartão sumiu talvez esteja em casa mas por segurança  | block_card | unknown | block_card |
| D-0061 | cancelar cartão | block_card | unknown | block_card |
| D-0062 | Prezados, por segurança solicito o cancelamento do meu cartão, que não localizo desde ontem. | block_card | unknown | block_card |
| D-0063 | oye una duda ya no voy a usar esta tarjeta la que tiene el chip roto o sea la vieja quiero cancelarl | block_card | unknown | block_card |
| D-0003 | Estimados, por medio de la presente manifiesto que no reconozco el cargo por trescientos cincuenta p | dispute_charge | dispute_charge | unknown |
| D-0018 | A quien corresponda: solicito la cancelación de un cargo recurrente de ciento ochenta pesos por un s | dispute_charge | dispute_charge | unknown |
| D-0019 | parce imagínese que estaba mirando el extracto y hay un pago en una tienda de Medellín por ciento cu | dispute_charge | dispute_charge | unknown |
| D-0021 | Respetados señores, desconozco la transacción por ciento cuarenta mil pesos realizada en Medellín, c | dispute_charge | dispute_charge | unknown |
| D-0030 | Solicito respetuosamente la aclaración de dos cargos idénticos por mil doscientos pesos efectuados e | dispute_charge | dispute_charge | out_of_scope |
| D-0033 | Cordialmente solicito la revisión de un cobro superior al valor acordado en un establecimiento hotel | dispute_charge | dispute_charge | unknown |
| D-0036 | Estimados: desconozco un débito mensual de cuatro mil pesos de una aplicación de juegos; solicito su | dispute_charge | dispute_charge | unknown |
| D-0067 | uy me parece que alguien me vio digitar la clave en el cajero y ahora tengo miedo entonces mejor blo | block_card | block_card | unknown |
| D-0083 | acceso no autorizado | account_takeover | account_takeover | unknown |
| D-0134 | hola eh queria saber si tengo seguro de vida no cartão ou como contrato um | out_of_scope | out_of_scope | unknown |
| D-0135 | seguros | out_of_scope | out_of_scope | unknown |
| D-0139 | quiero invertir unos veinte mil pesos en algo seguro o sea cetes o un fondo no sé qué me recomiendan | out_of_scope | out_of_scope | unknown |

</details>

## Calibración

Temperatura ajustada por NLL en las predicciones fuera de fold; ECE con 10 bins de igual ancho.

| sistema | ECE validación cruda → calibrada | ECE test | ECE test_style |
|---|---|---|---|
| lite | 0.192 → 0.019 | 0.036 | 0.033 |
| full | 0.105 → 0.019 | 0.023 | 0.037 |

![Diagrama de confiabilidad](figures/intent_reliability.png)

## Limitaciones

- El corpus lo escribieron asistentes de IA siguiendo una guía: es más limpio y prototípico que el tráfico real (de ahí el acuerdo casi perfecto entre anotadores). Los números absolutos son optimistas; el test de estilo no visto y la evaluación de punta a punta (`reports/eval.md`) son la referencia más realista.
- RuleRouter se ajustó en #54 con el split dev de `evals/cases` y con frases propias, no con este corpus; aun así, nadie ajustó las reglas mirando el test C/D/G.
- La guía da precedencia a disputa sobre pedido de humano ("quiero hablar con alguien por un cargo que no hice" = `dispute_charge`); RuleRouter hace lo contrario a propósito (#54). Esos casos cuentan como error de reglas aunque sean una decisión de diseño: son pocos (fila *disputa → handoff* de su matriz por ruta).
- `dispute_status` y `cancel_dispute` tienen un solo autor de train (F): es donde más se abstiene el modelo (pasa a aclarar, no a una acción). Más autores para esas dos intenciones es la mejora más barata.
- El mejor C quedó en el borde de la grilla (30) para todos los candidatos; no se amplió después de ver el test.
- n chico por intención (≈20–60 en test): por eso los IC por bootstrap de familias.

## Reproducir

```bash
pip install -e ".[ml,ml-train]"
PYTHONPATH=src python scripts/train_intent.py   # CPU, minutos; baja los modelos preentrenados a la caché de Hugging Face la primera vez
```

Python 3.12.2 · AMD64 · Intel64 Family 6 Model 165 Stepping 2, GenuineIntel · numpy 2.5.3 · scikit-learn 1.9.1.

