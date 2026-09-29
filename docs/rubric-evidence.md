# Mapa de evidencia para el jurado

Cada punto del enunciado → qué hicimos → dónde verificarlo (archivo, test o reporte).
Los tests se corren con `pytest -q` (offline, sin datos reales ni API keys). ⏳ = en curso, con su issue.

## 1. Problema sustentado con datos
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Motivos de contacto, demanda, calidad, restricciones | EDA de interacciones, PQR y transacciones. Las quejas son el 17% de los contactos con FCR de 43.6%; "Cargo no reconocido" + "Cobro indebido" = 36.5% de las quejas | [`reports/EDA_findings.md`](../reports/EDA_findings.md), [`reports/eda_output.txt`](../reports/eda_output.txt), gráficos en `docs/pitch/charts/` |
| Priorizar el flujo | Decisión escrita con alternativas descartadas | [ADR 0001](adr/0001-flujo-disputas.md) |
| Resultados esperados para cliente y negocio | Resolver en el primer contacto lo automatizable y derivar con contexto completo lo que no | [ADR 0001](adr/0001-flujo-disputas.md), [`docs/pitch/deck.md`](pitch/deck.md) |
| Proyección sobre la demanda real | Replay de quejas históricas (etiquetado como simulación) | ⏳ #30 |

## 2. Sistema de IA funcional
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Contexto conversacional y aclaraciones | Estado por conversación (checkpointer); pregunta cuando hay 0 o varias transacciones candidatas | `tests/test_agent.py::test_ambiguous_asks_which_then_resolves` |
| Respuestas ancladas en datos permitidos | Toda cifra sale de una herramienta; con LLM, un verificador determinista rechaza cifras o IDs inventados | `src/bankagent/responses.py`, `src/bankagent/llm_writer.py::verify_reply`, `tests/test_llm.py::test_writer_invented_amount_falls_back_to_template` |
| Reportar solo acciones verificadas | Las herramientas releen el estado después de actuar (`verified=True`); si no se verifica, pasa a un humano | `src/bankagent/tools.py`, `tests/test_agent.py::test_normal_path_dispute_and_block_with_confirmation` |
| Español y portugués | Detección de idioma, plantillas es/pt, escenarios de demo en pt-BR | `tests/test_agent.py::test_portuguese_fraud_signal_handoff`, [`docs/demo-script.md`](demo-script.md) |

## 3. Automatización controlada
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Qué responde, qué requiere confirmación, cuándo transfiere | Política declarativa con reglas identificadas (D01–D05 rechazo/informativa, H01–H04 humano); toda acción con confirmación | [`config/policy.yaml`](../config/policy.yaml), `tests/test_policy.py`, `tests/test_agent.py::test_repeat_complainer_and_suspended_go_to_human` |
| Permisos y política fuera del texto del modelo | El cliente sale del token de sesión, nunca de la conversación; transiciones del grafo declaradas y aplicadas | `tests/test_security.py::test_tools_refuse_other_customers_data`, `tests/test_security.py::test_undeclared_transition_fails_closed`, [ADR 0002](adr/0002-grafo-deterministico-con-llm-acotado.md) |
| Handoff con solicitud, hechos, acciones, evidencia y preguntas abiertas | Paquete estructurado en cada derivación | `tests/test_agent.py::test_high_amount_goes_to_human_with_handoff_packet`; evaluación humana ⏳ #32 |
| Propiedades demostradas (no solo casos) | Tests basados en propiedades y verificación de todas las rutas del grafo | ⏳ #31 |

## 4. Datos y ML con buenas prácticas
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Preparación repetible con contratos y validaciones | Contrato por tabla (tipos, dominios, FKs); filas inválidas a cuarentena con motivo | [`config/contracts.yaml`](../config/contracts.yaml), `tests/test_pipeline.py::test_contract_quarantines_invalid_rows` |
| Linaje y política de actualización | Manifiesto por corrida (archivos, filas, cuarentena, huella de la entrega); upsert idempotente con llegadas tardías | [`reports/data_quality.md`](../reports/data_quality.md), `tests/test_pipeline.py::test_rerun_is_idempotent_and_late_arrivals_upsert`, [`reports/snapshot_diff.md`](../reports/snapshot_diff.md) |
| Umbrales y splits justificados | Umbral de fraude calibrado con split temporal (test 2026: recall 72.4%, precisión 79.0%) | [ADR 0006](adr/0006-umbral-fraude.md), [`reports/fraud_threshold.md`](../reports/fraud_threshold.md), `tests/test_policy.py::test_fraud_threshold_boundary` |
| Etiquetas válidas, sin fuga | No entrenamos sobre transcripciones en plantilla (etiquetas inválidas); lo documentamos | [ADR 0003](adr/0003-sin-modelo-entrenado-en-datos-del-banco.md) |
| ≥1 componente aprendido contra una línea base | Clasificador de inyección preentrenado contra regex, sobre datasets públicos etiquetados | ⏳ #8/#9 |

## 5. Calidad medida y manejo de fallas
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Datos incorrectos o faltantes | Cuarentena; nulos de `fraud_score` y `merchant_name` manejados y documentados | `tests/test_pipeline.py`, [`reports/data_quality.md`](../reports/data_quality.md) |
| Sesión expirada | Respuesta segura sin herramientas | `tests/test_security.py::test_no_session_and_expired_session` |
| Acceso no autorizado | Herramientas niegan recursos ajenos; bloqueo tras 3 intentos | `tests/test_security.py::test_tools_refuse_other_customers_data`, `tests/test_audit.py::test_forbidden_access_counts_towards_lockout` |
| Inyección de prompts | Guard + inyección indirecta desde los datos + cliente señuelo que nunca se filtra | `tests/test_security.py::test_indirect_injection_in_data_has_no_effect`, `tests/test_security.py::test_canary_never_leaks_across_all_conversations`; con datasets públicos ⏳ #8 |
| Fallas de herramientas | Reintentos acotados en errores transitorios; si persiste, humano | `tests/test_agent.py::test_transient_tool_failure_is_retried`, `tests/test_agent.py::test_persistent_tool_failure_hands_off` |
| Concurrencia | Fuga entre clientes con conexiones compartidas: encontrada con prueba de carga y corregida | `tests/test_concurrency.py::test_concurrent_reads_never_mix_customers`, [`reports/capacity.md`](../reports/capacity.md) |
| Métricas del enunciado sobre casos reservados | Resolución segura, contención, escalamiento, inseguros n/N, p50/p95, costo; por idioma y segmento | ⏳ #12/#13 |

## 6. Ruta creíble a producción
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Trazas, reintentos acotados, alternativa segura | Traza por nodo (latencia, herramientas, intentos); LLM con fallback a reglas | `src/bankagent/graph.py`, `src/bankagent/observability.py`, `tests/test_llm.py::test_router_failures_fall_back_to_rules` |
| Setup reproducible | Tests sin datos ni keys; pipeline e informes con un comando cada uno | [`README.md`](../README.md) |
| Capacidad, monitoreo, acceso, retención, trabajo restante | Prueba de carga, SLOs con alertas, runbook, retención, pendientes priorizados | [`docs/operations.md`](operations.md), [`reports/capacity.md`](../reports/capacity.md) |
| Explicaciones desde reglas y registros, no desde razonamiento oculto | Decisión = IDs de reglas + hechos verificados; log de auditoría con cadena de hashes | `tests/test_audit.py::test_tampering_is_detected`, [`docs/threat-model.md`](threat-model.md) |

## Límites declarados (lo que no hacemos o no pudimos medir)
- Todo el texto del dataset está en español; el portugués se prueba con mensajes y traducciones del equipo, declarados como tales.
- El dataset no vincula quejas con transacciones: la prevalencia de fraude entre cargos disputados no es medible.
- El bucket trae dos generaciones del dataset; usamos `data/` y registramos su huella.
- El LLM está implementado pero **apagado**: no hay costo ni latencia reales medidos. Todas las métricas son de la línea base de reglas y plantillas.
- Seguridad: [`docs/threat-model.md`](threat-model.md), sección de riesgos residuales.
