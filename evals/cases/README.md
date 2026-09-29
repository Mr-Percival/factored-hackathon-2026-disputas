# Casos de evaluación reservados

> **Procedencia:** casos y etiquetas **generados por el equipo por construcción** sobre los datos **sintéticos**
> del organizador (`serving.duckdb`, as_of 2026-06-17). **No son tráfico real** ni anotación humana independiente.

| Archivo | Contenido |
|---|---|
| `test.jsonl` | Conjunto reservado: 116 casos principales + 44 variantes de equidad (11 grupos × 4 dialectos). **Es el único que se reporta.** |
| `dev.jsonl` | Conjunto de desarrollo: 56 principales + 20 de equidad. Se usa para ajustar la línea base. |
| `manifest.json` | Semilla, versión de política, conteos pedidos y obtenidos, verificación cruzada con la política, sha256 de cada archivo. |

Regenerar (determinista, misma semilla → mismos archivos):
```bash
python -m bankagent.evals.cases --db data/serving.duckdb --out evals/cases
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
verificada, inyectadas por el runner), `missing_data` (mensaje vago, con o sin detalles después).

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
| dev (v1) | `origin/main` | 32/56 | 12/22 | 1/5 grupos |
| dev (v1) | ajustado | 55/56 | 21/22 | 5/5 grupos |
| **test (v2, reservado)** | `origin/main` | 69/116 | 33/60 | 3/11 grupos |
| **test (v2, reservado)** | ajustado | **101/116** | **53/60** | **5/11 grupos** |

El reporte completo (con variabilidad, desgloses y fallas) está en [`reports/eval.md`](../../reports/eval.md).

## Limitaciones
Un solo proceso de etiquetado (sin segundo anotador); el cliente simulado es cooperativo y consistente; el portugués lo
escribió un equipo hispanohablante; no hay clientes brasileños en el dataset, así que los casos pt-BR usan clientes de
MX/CO/AR.
