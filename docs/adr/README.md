# Registro de decisiones (ADR)

Cada decisión de arquitectura con su contexto, las alternativas descartadas y sus consecuencias. Plantilla:
[`0000-template.md`](0000-template.md). Un ADR no se reescribe: si una decisión cambia, se agrega uno nuevo que
reemplaza al anterior y se actualiza el estado aquí.

| ADR | Decisión | Estado | Evidencia |
|---|---|---|---|
| [0001](0001-flujo-disputas.md) | Flujo: disputa de cargos no reconocidos + bloqueo de tarjeta | aceptada | [`reports/EDA_findings.md`](../../reports/EDA_findings.md) |
| [0002](0002-grafo-deterministico-con-llm-acotado.md) | Grafo determinista (LangGraph) con el modelo acotado a interpretar y redactar | aceptada | [`graph-paths.md`](../graph-paths.md), `tests/test_graph_paths.py` |
| [0003](0003-sin-modelo-entrenado-en-datos-del-banco.md) | No entrenar sobre los textos del dataset; el componente aprendido se evalúa con etiquetas válidas | aceptada | [`reports/EDA_findings.md`](../../reports/EDA_findings.md) |
| [0004](0004-llm-acotado-router-writer.md) | Router y writer con LLM: modelos, versiones, fallback y privacidad | aceptada · implementado, **apagado** en la demo (sin API paga) | `tests/test_llm.py` |
| [0005](0005-deteccion-inyeccion.md) | Detección de inyección: regex por defecto, clasificador preentrenado opt-in | aceptada | [`reports/injection_eval.md`](../../reports/injection_eval.md) |
| [0006](0006-umbral-fraude.md) | Umbral de `fraud_score` = 30 para derivar a un analista (H03), calibrado con split temporal | aceptada | [`reports/fraud_threshold.md`](../../reports/fraud_threshold.md) |
| [0007](0007-evaluacion-casos-por-construccion.md) | Evaluación con casos generados por construcción, divididos por cliente y por redacción | aceptada | [`evals/cases/README.md`](../../evals/cases/README.md), [`reports/eval.md`](../../reports/eval.md) |
| [0008](0008-frontend-web.md) | Demo web: FastAPI + React en un contenedor, sesión por cookie opaca | aceptada (reemplaza la demo Streamlit) | [`web/README.md`](../../web/README.md), [`reports/a11y_security_audit.md`](../../reports/a11y_security_audit.md) |
| [0009](0009-router-aprendido.md) | Router de intención aprendido (local, CPU) evaluado contra RuleRouter; default de la demo | aceptada | [`reports/intent_router.md`](../../reports/intent_router.md), [`reports/eval_router.md`](../../reports/eval_router.md) |
