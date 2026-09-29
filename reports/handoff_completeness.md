# Completitud de los paquetes de handoff (verificador determinista)

Generado por `python -m bankagent.evals.human_kit check`. Es la contraparte automática de la evaluación humana (`evals/human/RUBRIC.md`): mide si el paquete trae lo necesario y si es **consistente con la política** (re-evaluando `config/policy.yaml` con los hechos del paquete), no si es útil para el asesor.

Política: `2026-09-29.1`.

| Origen | Paquetes | Completos | % |
|---|---|---|---|
| escenarios de demo (docs/demo/demo_customers.json) | 5 | 5 | 100.0% |
| kit humano: paquetes reales | 30 | 30 | 100.0% |
| kit humano: controles degradados (se esperan incompletos) | 5 | 0 | 0.0% |

## Fallas por chequeo

- **kit humano: controles degradados (se esperan incompletos)**: `hechos_cliente` × 1, `hechos_transaccion` × 1, `pedido_no_vacio` × 1, `preguntas_no_vacias` × 1, `reglas_reproducibles` × 3

## Paquetes incompletos

- `kit humano: controles degradados (se esperan incompletos)` · `P05` (`H02_high_amount`): **hechos_transaccion** transacción sin ['transaction_id', 'transaction_date', 'amount', 'currency', 'transaction_status', 'transaction_type']; **hechos_cliente** sin ['customer_status', 'segment', 'complaints_last_90d', 'is_repeat_complainer']; **reglas_reproducibles** no se puede re-evaluar la política sin hechos
- `kit humano: controles degradados (se esperan incompletos)` · `P07` (`H02_high_amount`): **reglas_reproducibles** con los hechos del paquete la política dispara [], el paquete dice ['H02_high_amount']
- `kit humano: controles degradados (se esperan incompletos)` · `P12` (`H04_repeat_complainer`): **reglas_reproducibles** con los hechos del paquete la política dispara ['H02_high_amount'], el paquete dice ['H04_repeat_complainer']
- `kit humano: controles degradados (se esperan incompletos)` · `P29` (`H04_repeat_complainer`): **preguntas_no_vacias** sin preguntas abiertas
- `kit humano: controles degradados (se esperan incompletos)` · `P34` (`H01_customer_not_active`): **pedido_no_vacio** sin mensajes del cliente
