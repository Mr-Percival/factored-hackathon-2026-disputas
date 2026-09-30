# Mapa de evidencia para el jurado

Cada punto del enunciado → qué hicimos → dónde verificarlo (archivo, test o reporte).
Los tests se corren con `pytest -q` (offline, sin datos reales ni API keys). Las referencias de este archivo las
verifica `python scripts/check_docs.py` en la CI (falla si un archivo, ancla o test citado no existe).
⏳ = pendiente, con lo que falta.

**Sistema de la demo:** router de intención aprendido (`embeddings`, lite) + `RuleRouter` para slots y consentimiento
+ plantillas; el LLM está implementado pero apagado (sin API paga). Número principal: 109/115 resultados correctos,
55/57 resoluciones automáticas seguras y 0/115 inseguros en el test congelado
([`reports/eval_router.md`](../reports/eval_router.md); segunda medición, con la fuga leve declarada en
[`evals/cases/README.md`](../evals/cases/README.md)).

## 1. Problema sustentado con datos
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Motivos de contacto, demanda, calidad, restricciones | EDA de interacciones, PQR y transacciones. Las quejas son el 17% de los contactos con FCR de 43.6%; "Cargo no reconocido" + "Cobro indebido" = 36.5% de las quejas | [`reports/EDA_findings.md`](../reports/EDA_findings.md), [`reports/eda_output.txt`](../reports/eda_output.txt), gráficos en `docs/pitch/charts/` |
| Priorizar el flujo | Decisión escrita con alternativas descartadas | [ADR 0001](adr/0001-flujo-disputas.md) |
| Resultados esperados para cliente y negocio | Resolver en el primer contacto lo automatizable y derivar con contexto completo lo que no | [ADR 0001](adr/0001-flujo-disputas.md), [`docs/pitch/deck.md`](pitch/deck.md) |
| Proyección sobre la demanda real | Replay de 1.000 quejas históricas por el agente real, cada una juzgada a su fecha, + modo sombra contra el desenlace histórico. **SIMULACIÓN:** 33.3% [30.4–36.3%] resueltas solas y seguras, 0 acciones inseguras; la proyección de negocio va aparte y rotulada | [`reports/replay.md`](../reports/replay.md), `tests/test_replay.py::test_point_in_time_search_hides_later_transactions`, `::test_run_on_fixture_writes_a_labeled_report` |

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
| Handoff con solicitud, hechos, acciones, evidencia y preguntas abiertas | Paquete estructurado en cada derivación | `tests/test_agent.py::test_high_amount_goes_to_human_with_handoff_packet`, `tests/test_handoff.py::test_every_handoff_validates_against_the_schema`, [`handoff.schema.json`](handoff.schema.json); completitud automática: [`reports/handoff_completeness.md`](../reports/handoff_completeness.md), `tests/test_human_eval.py::test_completeness_checker_accepts_real_and_rejects_degraded`; evaluación humana: kit listo ([`evals/human/RUBRIC.md`](../evals/human/RUBRIC.md)), ⏳ calificaciones pendientes ([`reports/human_eval.md`](../reports/human_eval.md)) |
| Propiedades demostradas (no solo casos) | Invariantes I1–I8 con Hypothesis sobre conversaciones aleatorias con varios clientes, fallas y vencimientos (perfil `ci`: 200 conversaciones, 0 violaciones; la corrida `deep` queda por publicar) + verificación estática de los 19 caminos del grafo y de las 588 combinaciones que llevan a `act` | `tests/test_properties.py::test_conversation_invariants`, `::test_policy_oracle_matches_yaml_rules`, `tests/test_graph_paths.py::test_act_is_only_reachable_from_understand`, `::test_understand_routes_to_act_only_on_fresh_confirmation`, [`docs/threat-model.md`](threat-model.md#propiedades-demostradas), [`docs/graph-paths.md`](graph-paths.md) |

## 4. Datos y ML con buenas prácticas
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Preparación repetible con contratos y validaciones | Contrato por tabla (tipos, dominios, FKs); filas inválidas a cuarentena con motivo | [`config/contracts.yaml`](../config/contracts.yaml), `tests/test_pipeline.py::test_contract_quarantines_invalid_rows` |
| Linaje y política de actualización | Manifiesto por corrida (archivos, filas, cuarentena, huella de la entrega); upsert idempotente con llegadas tardías | [`reports/data_quality.md`](../reports/data_quality.md), `tests/test_pipeline.py::test_rerun_is_idempotent_and_late_arrivals_upsert`, [`reports/snapshot_diff.md`](../reports/snapshot_diff.md) |
| Umbrales y splits justificados | Umbral de fraude calibrado con split temporal (test 2026: recall 72.4%, precisión 79.0%) | [ADR 0006](adr/0006-umbral-fraude.md), [`reports/fraud_threshold.md`](../reports/fraud_threshold.md), `tests/test_policy.py::test_fraud_threshold_boundary` |
| Etiquetas válidas, sin fuga | No entrenamos sobre transcripciones en plantilla (etiquetas inválidas). El router aprendido se entrena con un corpus propio etiquetado con guía, dividido por **autor** y por familia de paráfrasis, con un test de estilo no visto; el test de punta a punta está congelado por hash y dividido por cliente y por redacción, con su uso declarado (segunda medición y una fuga leve en #54) | [ADR 0003](adr/0003-sin-modelo-entrenado-en-datos-del-banco.md), [ADR 0007](adr/0007-evaluacion-casos-por-construccion.md), [`corpus/intent/GUIA_ETIQUETADO.md`](../corpus/intent/GUIA_ETIQUETADO.md), [`evals/cases/README.md`](../evals/cases/README.md), `tests/test_evals.py::test_frozen_test_set_is_not_overwritten` |
| ≥1 componente aprendido contra una línea base | **Router de intención aprendido** (n-gramas de caracteres + regresión logística calibrada + abstención, 0.2 MB, CPU) contra `RuleRouter`: macro-F1 0.877 [0.83, 0.91] vs 0.548 y acción equivocada 1.6% vs 18.6% (n=306); de punta a punta 109/115 vs 104/115 correctos y 0 vs 7 transferencias faltantes. Está en el camino crítico de la demo, con fallback visible a reglas. Además: clasificador de inyección preentrenado contra regex (AUC 0.97 vs 0.55), que quedó opt-in por sus falsas alarmas en mensajes bancarios (20/58) | [ADR 0009](adr/0009-router-aprendido.md), [`reports/intent_router.md`](../reports/intent_router.md), [`reports/eval_router.md`](../reports/eval_router.md), `tests/test_intent_router.py::test_missing_model_falls_back_to_rules_and_says_so`, `::test_abstention_never_backs_off_into_an_action`; [ADR 0005](adr/0005-deteccion-inyeccion.md), [`reports/injection_eval.md`](../reports/injection_eval.md) |

## 5. Calidad medida y manejo de fallas
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Datos incorrectos o faltantes | Cuarentena; nulos de `fraud_score` y `merchant_name` manejados y documentados | `tests/test_pipeline.py`, [`reports/data_quality.md`](../reports/data_quality.md) |
| Sesión expirada | Respuesta segura sin herramientas | `tests/test_security.py::test_no_session_and_expired_session` |
| Acceso no autorizado | Herramientas niegan recursos ajenos; bloqueo tras 3 intentos | `tests/test_security.py::test_tools_refuse_other_customers_data`, `tests/test_audit.py::test_forbidden_access_counts_towards_lockout` |
| Inyección de prompts | Guard + inyección indirecta desde los datos + cliente señuelo que nunca se filtra; datasets públicos (daño 0/2.531 aun sin guard) y **red team adaptativo** (#33): 3 rondas de ~100 ataques del equipo (consentimiento manipulado, unicode, envenenamiento de slots, inyección hacia el paquete del asesor, abuso de sesión/hilo/canal HTTP), cada una contra lo ya corregido. Encontró daño real que los datasets no cubrían (ej. "después te confirmo" abría la disputa; un intruso bloqueaba el hilo ajeno; una IP agotaba las sesiones), se corrigió la raíz y cada ataque quedó como regresión | `tests/test_security.py::test_indirect_injection_in_data_has_no_effect`, `::test_canary_never_leaks_across_all_conversations`, [`reports/injection_eval.md`](../reports/injection_eval.md), [`reports/redteam.md`](../reports/redteam.md), `tests/test_redteam.py` (corpus `evals/redteam/` completo en CI, ambos routers, guard activo y apagado) |
| Fallas de herramientas | Reintentos acotados en errores transitorios; si persiste, humano | `tests/test_agent.py::test_transient_tool_failure_is_retried`, `tests/test_agent.py::test_persistent_tool_failure_hands_off` |
| Concurrencia | Fuga entre clientes con conexiones compartidas: encontrada con prueba de carga y corregida | `tests/test_concurrency.py::test_concurrent_reads_never_mix_customers`, [`reports/capacity.md`](../reports/capacity.md) |
| Medición ciega (overfitting) | Test v3 escrito por un autor aislado (solo leyó la política y la base), congelado por hash y corrido **una vez**: **0/80** acciones no esperadas (seguridad intacta) pero utilidad **43/80** (vs 109/115 en el test propio). Cada desacuerdo se clasificó (37/37 fallas propias; 20 por consentimiento estricto, el costo del arreglo del red team) y se arregló de forma genérica con frases propias; la segunda corrida (76/80) se reporta como **no ciega** y queda pedido un test v4 | [`reports/eval_blind_v3.md`](../reports/eval_blind_v3.md), [`reports/eval_blind_v3_rerun.md`](../reports/eval_blind_v3_rerun.md), [`evals/cases/README.md`](../evals/cases/README.md#test-v3-ciego-usado-una-vez-71), `tests/test_consent.py::test_consent_grammar_accepts_restated_actions_and_nothing_else` |
| Métricas del enunciado sobre casos reservados | Resolución segura, contención, escalamiento, inseguros n/N con cota, p50/p95, costo; por idioma, dialecto y segmento; variabilidad entre 3 corridas; líneas base B0 (todo a humano) y B1 (sin política: 82/115 inseguros) | [`reports/eval_router.md`](../reports/eval_router.md), [`reports/eval.md`](../reports/eval.md), [ADR 0007](adr/0007-evaluacion-casos-por-construccion.md), `tests/test_evals.py::test_action_without_confirmation_turn_is_unsafe`, `::test_baselines_b0_transfers_and_b1_acts_without_policy`, `tests/test_fairness.py::test_same_dispute_same_decision_in_every_dialect` |

## 6. Ruta creíble a producción
| Qué pide | Qué hicimos | Evidencia |
|---|---|---|
| Trazas, reintentos acotados, alternativa segura | Traza por nodo (latencia, herramientas, intentos); LLM con fallback a reglas | `src/bankagent/graph.py`, `src/bankagent/observability.py`, `tests/test_llm.py::test_router_failures_fall_back_to_rules` |
| Setup reproducible | Tests sin datos ni keys; pipeline e informes con un comando cada uno; dependencias con hash y acciones fijadas por SHA | [`README.md`](../README.md), [`requirements/ci.lock`](../requirements/ci.lock), `tests/test_supply_chain.py` |
| CI y deploy | CI: tests, guardia de regresión con ambos routers (`scripts/ci_guard.py`: 0 inseguros, handoffs completos, piso de exactitud), web (lint, tipos, tests), e2e con Playwright e imagen Docker. Deploy: GitHub Actions construye la base de demo en un runner efímero (los datos nunca pasan por el repo), verifica los 14 escenarios, publica la imagen en GHCR privado y la despliega en Render. ⏳ link público pendiente | [`.github/workflows/ci.yml`](../.github/workflows/ci.yml), [`.github/workflows/deploy.yml`](../.github/workflows/deploy.yml), [`docs/operations.md`](operations.md#deploy-de-la-demo-render) |
| Capacidad, monitoreo, acceso, retención, trabajo restante | Prueba de carga, SLOs con alertas, runbook, retención, pendientes priorizados | [`docs/operations.md`](operations.md), [`reports/capacity.md`](../reports/capacity.md) |
| Explicaciones desde reglas y registros, no desde razonamiento oculto | Decisión = IDs de reglas + hechos verificados; log de auditoría con cadena de hashes | `tests/test_audit.py::test_tampering_is_detected`, [`docs/threat-model.md`](threat-model.md) |
| Solución desplegable con demo que muestre la ingeniería | API FastAPI + SPA React en un contenedor: escenarios con guion, chat, "Por qué respondió así" (qué entendió, traza, reglas, hechos) y consola del asesor | [ADR 0008](adr/0008-frontend-web.md), [`web/README.md`](../web/README.md), `Dockerfile` (job `image` de la CI lo construye y prueba), capturas en `docs/pitch/screens/escena{1,2,3}.png` |
| Canal seguro | Token del agente solo en el servidor (cookie HttpOnly/SameSite=Strict con id opaco), CSP estricta, Origin, límites de tamaño y de ritmo, errores sin eco | `tests/test_api.py::test_cookie_is_httponly_strict_and_token_never_leaves_the_server`, `::test_security_headers_everywhere`, `::test_rate_limit_returns_429`, `::test_oversized_and_blank_text_are_rejected_without_echo`, `web/e2e/security.spec.ts` (cabeceras, cookie y almacenamiento vistos desde el navegador; HTML inyectado no se ejecuta), [`reports/a11y_security_audit.md`](../reports/a11y_security_audit.md) |
| Guion de demo verificado de punta a punta por HTTP | Cada escenario del JSON se reproduce por la API y se compara con el resultado esperado | `tests/test_api.py::test_every_fixture_scenario_plays_as_scripted` |
| Concurrencia en el canal | Clientes en paralelo por HTTP (incluido el señuelo) nunca ven datos ajenos | `tests/test_api.py::test_parallel_customers_only_see_their_own_data` |
| Accesibilidad (WCAG 2.2 AA) | Resultado con ícono + texto, región viva para respuestas, teclado, foco visible, tema claro/oscuro, pestañas APG en móvil; auditoría automatizada con axe-core (0 violaciones serias/críticas en 14 estados: inicial, resuelta, handoff, claro/oscuro, móvil 390×844) y recorrido solo con teclado | [`reports/a11y_security_audit.md`](../reports/a11y_security_audit.md), `web/e2e/a11y.spec.ts` (job `e2e` de la CI), `web/src/App.test.tsx`, ESLint `jsx-a11y` strict en la CI |

## Límites declarados (lo que no hacemos o no pudimos medir)
- Todo el texto del dataset está en español; el portugués se prueba con mensajes y traducciones del equipo, declarados como tales.
- El dataset no vincula quejas con transacciones: la prevalencia de fraude entre cargos disputados no es medible.
- El bucket trae dos generaciones del dataset; usamos `data/` y registramos su huella.
- El LLM está implementado pero **apagado**: no hay costo ni latencia reales medidos. Todas las métricas son de reglas o del router aprendido local, con plantillas.
- El test de punta a punta ya se midió dos veces y tuvo una fuga leve declarada (#54): una medición limpia de la próxima versión necesita un test v3 escrito por otra persona.
- La evaluación humana de los handoffs tiene el kit listo pero todavía no tiene calificaciones.
- Seguridad: [`docs/threat-model.md`](threat-model.md), sección de riesgos residuales.
