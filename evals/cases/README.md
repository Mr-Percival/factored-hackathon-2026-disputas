# Casos de evaluación reservados

> **Procedencia:** casos y etiquetas **generados por el equipo por construcción** sobre los datos **sintéticos**
> del organizador (`serving.duckdb`, as_of 2026-06-17). **No son tráfico real** ni anotación humana independiente.

| Archivo | Contenido |
|---|---|
| `test.jsonl` | Conjunto reservado **congelado**: 115 casos principales + 44 variantes de equidad (11 grupos × 4 dialectos). **Es el único que se reporta.** |
| `dev.jsonl` | Conjunto de desarrollo: 61 principales + 20 de equidad. Es el único que se usa para ajustar routers. |
| `manifest.json` | Semilla, versión de política, conteos pedidos y obtenidos, verificación cruzada con la política, sha256 de cada archivo. |

## Test congelado
- `test.jsonl` sha256 **`424d0f78dc21efdf2e659db03876f1717fa9419dacff9c1acd2cf09d1a89040b`**, congelado en el commit
  `220ee5e` (política `2026-09-29.1`).
- **No se ajusta ningún router mirando test** (ni el RuleRouter, ni #38–#42, ni el de embeddings). Se ajusta con dev y
  con frases propias. Test existe para medir antes y después sin fuga.
- El generador es determinista (misma semilla → mismos archivos) y **se niega a reescribir `test.jsonl`** si el
  contenido cambiaría. Solo lo hace con `--force`, que invalida la comparación con reportes previos y debe quedar
  documentado aquí. El runner verifica el hash y lo imprime en `reports/eval.md`.

```bash
python -m bankagent.evals.cases --db data/serving.duckdb --out evals/cases   # verifica/regenera (test no cambia)
python -m bankagent.evals.run --db data/serving.duckdb --system b0 --system b1 --system rules --repeats 3
```

## Cómo se construye un caso
1. **Cliente y transacción reales.** Para cada tipo de caso se eligen clientes y, si aplica, una transacción objetivo
   por sus atributos crudos. Ejemplos: `Declined` → D02, más de 150 días → D05, monto ≥ umbral por moneda → H02,
   `fraud_score ≥ 60` → H03, cliente no activo → H01, reclamante recurrente → H04. Para el caso normal: aprobada,
   reciente, bajo el umbral, sin señal de fraude, cliente activo y sin reclamos.
2. **Etiqueta desde la especificación.** El resultado, la regla y las acciones esperadas salen de `config/policy.yaml`
   aplicada a esos atributos. Además, cada candidato se verifica con el motor de política; si no coinciden, se
   descarta (0 descartes en la versión actual).
3. **El mensaje identifica la transacción.** Ninguna otra transacción disputable del cliente cae en el monto
   declarado ±10% dentro de la ventana de fecha que la frase afirma. La ventana usa la semántica natural de la frase
   ("antier" = hoy − 2 días), no la del router. Los casos `ambiguous` tienen 2 a 5 coincidencias a propósito.
4. **Redacción por dialecto.** Las plantillas están escritas a mano (`src/bankagent/evals/lexicon.py`) para es-MX,
   es-CO, es-AR (voseo) y pt-BR, con montos en formato local (`$1,200.50`, `$ 1.200,50`, `45 mil pesos`,
   `1,2 millones`, `23 lucas`), fechas relativas y textuales, y ruido realista: tildes omitidas, seseo, `vc`/`nao`
   y letras invertidas.
5. **Guion del cliente.** `turns` tiene mensajes `say` (se envían mientras el caso sigue abierto), `say_after` (el
   cliente vuelve a escribir aunque el caso terminó, p. ej. reclamar dos veces el mismo cargo), y respuestas
   condicionales `option`, `option_missing` y `confirm`. Estas se usan solo si el agente pregunta. `{n}` y `{ordinal}`
   se completan con la posición real de la transacción objetivo en la lista que muestra el agente.

## División dev / test
- **Por cliente:** hash de `customer_id` (30% dev). Ningún cliente aparece en ambas.
- **Por redacción:** dev usa las plantillas **v1** y test las **v2**. Las v2 se escribieron **después** de ajustar el
  RuleRouter con dev y no se usaron para ajustarlo. La razón es que un primer borrador de test compartía plantillas
  con dev: con él, la línea base pasaba de 77/115 a 114/115 correctos solo por haberse ajustado con las mismas frases.
  Ese número era optimista y se descartó.

## Categorías
`normal` (disputa, cancelación y bloqueo de tarjeta), `ambiguous`, `policy_reject` (D01–D05),
`handoff_high_amount`, `handoff_fraud`, `handoff_repeat`, `handoff_inactive`, `out_of_scope`, `unknown`,
`adversarial_access` (pide datos o acciones sobre otro cliente real, con marcadores de la víctima para detectar fugas),
`expired_session` (sesión vencida a mitad o inexistente), `tool_failure` (falla persistente, transitoria o acción no
verificada, inyectadas por el runner), `missing_data` (mensaje vago, con o sin detalles después),
`security_lockout` (insiste 3 veces en pedir datos ajenos: la política de strikes debe transferir a un humano).

## Esquema (una línea por caso)
```jsonc
{"id": "C001", "suite": "main|fairness", "fairness_group": "G01|null", "kind": "normal", "category": "normal",
 "language": "es", "dialect": "es-MX", "customer_id": "CLI-…", "segment": "Basic", "country": "México",
 "customer_status": "Active", "split": "test",
 "turns": [{"when": "say|say_after|option|option_missing|confirm", "text": "…"}],
 "target": {"transaction_id": "TRX-…", "product_id": "PRD-…", "amount": 485.22, "currency": "USD", "date": "…", …},
 "setup": {"expire_before_turn": 2} | {"token": "invalid"} | {"fail": {"tool": "search_transactions", "mode": "persistent"}},
 "victim": {"customer_id": "CLI-…", "markers": ["****1234", "…"]} | null,
 "labels": {"expected_outcome": "resolved", "acceptable_outcomes": ["resolved"], "expected_rule_id": null,
            "should_escalate": false, "expected_action": "dispute|block|none",
            "expected_actions": [{"type": "dispute", "id": "TRX-…"}, {"type": "block", "id": "PRD-…"}],
            "confirm_answer": "yes|no|null", "in_scope": true}}
```

## Ajustes a la línea base (RuleRouter) y números antes/después
Se ajustó `src/bankagent/understanding.py` **solo con fallas de dev**: la palabra clave `no reconheco` estaba mal
(el portugués real es `não reconheço`), "tarjeta de crédito" caía en fuera de alcance, las fechas ("el 9 de junio",
"hace 6 días") se leían como monto, faltaban `mil`/`millones`/`lucas`, voseo y regionalismos (`desconocer`,
`bloqueala`, `va`, `de una`), ordinales ("la segunda"), y las fechas sin año en el futuro no retrocedían al año
anterior. Los casos de dev que siguen fallando tienen errores de tipeo (`hise`, `reconosco`) y se dejaron así para no
sobreajustar.

| Conjunto | Router | Correctos | Resolución automática segura | Acuerdo entre dialectos |
|---|---|---|---|---|
| dev (v1) | `origin/main` (`50f040d`) | 41/61 | 15/25 | 1/5 grupos |
| dev (v1) | ajustado | 58/61 | 24/25 | 5/5 grupos |
| **test (v2, congelado)** | `origin/main` (`50f040d`) | 67/115 | 28/57 | 2/11 grupos |
| **test (v2, congelado)** | ajustado | **93/115** | **46/57** | **6/11 grupos** |

En los dos casos es la misma política (`2026-09-29.1`) y el mismo grafo; solo cambia `understanding.py`.

### Segunda ronda: robustez conversacional (#54)
| Conjunto | Versión | Correctos | Resolución automática segura | Transf. faltantes / innecesarias | Otro idioma | Inseguros |
|---|---|---|---|---|---|---|
| **test (v2, congelado)** | después de #48 | 93/115 | 46/57 | 11 / 0 | 17 | 0 |
| **test (v2, congelado)** | después de #54 | **102/115** | **49/57** | **7 / 3** | **4** | **0** |

**Uso del test declarado (honestidad metodológica).** En #54 nadie abrió los casos de test ni los resultados por
caso: se ajustó con dev, con frases propias etiquetadas y con los ejemplos de los issues. Pero **se hizo una ronda
de arreglos genéricos después de ver los números agregados** de una corrida sobre test (93 correctos, 3
transferencias innecesarias). Eso es una fuga leve: el test ya no es completamente ciego para esta versión. Las 3
transferencias innecesarias no se diagnosticaron justamente para no mirar casos. Para una medición limpia de la
próxima versión hay que construir un test v3 con redacciones nuevas escritas por otra persona.

El reporte completo (con variabilidad, desgloses y fallas) está en [`reports/eval.md`](../../reports/eval.md).

## Limitaciones
Un solo proceso de etiquetado (sin segundo anotador); el cliente simulado es cooperativo y consistente; el portugués lo
escribió un equipo hispanohablante; no hay clientes brasileños en el dataset, así que los casos pt-BR usan clientes de
MX/CO/AR.
