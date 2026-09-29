# Evaluación offline: línea base contra agente

> Generado por `python -m bankagent.evals.run --split test --repeats 3 --system rules --system embeddings` · commit `dbca68c` · 2026-09-29 02:34. No editar a mano: volver a correr el comando.

> **Qué es esto:** una medición OFFLINE sobre casos generados por el equipo con un cliente SIMULADO por guion, contra datos sintéticos del organizador. No es tráfico real ni una prueba con usuarios.

> **Segunda medición (PR #64, después de correcciones).** La primera medición de este test (PR #53: `rules` 102/115,
> `embeddings` 106/115, 2 paquetes de handoff incompletos, acuerdo por dialecto 10/11 vs 9/11) motivó correcciones
> que se diagnosticaron **solo** con el split dev (`evals/cases/dev.jsonl` y un dev ampliado con otras semillas del
> mismo generador, solo clientes y plantillas de dev), los escenarios de la demo, el kit humano y conversaciones
> escritas por el equipo; nunca con casos ni salidas por caso de test. Este test ya no es "visto una sola vez": es
> la segunda vez que se mide, y así debe leerse. Las correcciones cambian a los dos sistemas (grafo, handoff y
> RuleRouter son compartidos). Este archivo conserva SOLO las tablas agregadas (secciones 1–5, 11 y 12); el detalle
> por caso queda en `data/evals/results.json` (no versionado) y no se consultó.

## 1. Resumen


Conjunto **test** reservado: **115 casos** (principal) + **44** variantes de equidad (11 grupos × 4 dialectos). 3 corrida(s) por sistema. Valores de la corrida 1; la variabilidad está en la sección 5.

| Métrica (test, n=115) | `rules` | `embeddings` |
|---|---|---|
| Resolución automática segura / casos en alcance | 51/57 (89.5%) | 55/57 (96.5%) |
| Resolución automática segura / intentos de automatización | 51/54 (94.4%) | 55/55 (100.0%) |
| Resultado correcto (todos los casos) | 104/115 (90.4%) | 109/115 (94.8%) |
| Contención (sin transferencia) | 81/115 (70.4%) | 74/115 (64.3%) |
| … de la cual con resultado incorrecto | 10/81 (12.3%) | 0/74 (0.0%) |
| Transferencias correctas / debían transferirse | 31/38 (81.6%) | 38/38 (100.0%) |
| Transferencias útiles (paquete completo) / correctas | 31/31 (100.0%) | 35/38 (92.1%) |
| Transferencias faltantes | 7/38 (18.4%) | 0/38 (0.0%) |
| Transferencias innecesarias | 3/77 (3.9%) | 3/77 (3.9%) |
| Casos con resultado inseguro (cota sup. 95%) | 0/115 (0.0%) (≤ 2.6%) | 0/115 (0.0%) (≤ 2.6%) |
| Casos con alguna respuesta en otro idioma | 4/115 (3.5%) | 4/115 (3.5%) |
| Latencia por caso p50 / p95 | 87 ms / 152 ms | 90 ms / 146 ms |
| Costo por caso procesado | US$ 0.0000 | US$ 0.0000 |
| Costo por resolución automática segura | US$ 0.0000 | US$ 0.0000 |
| Acuerdo de decisión entre dialectos (grupos) | 10/11 (90.9%) | 10/11 (90.9%) |

| Sistema | Qué es |
|---|---|
| `rules` | Agente v1: grafo + RuleRouter + plantillas (política y confirmación) |
| `embeddings` | Agente con router aprendido (char2-5-tfidf) + plantillas |

## 2. Carga de trabajo y calidad de etiquetas


- **Origen:** Casos y etiquetas generados por el equipo por construcción sobre datos sintéticos del organizador; no son tráfico real ni anotación humana independiente.
- **Construcción:** generador determinista `bankagent.evals.cases` (semilla 20261005), clientes y transacciones reales de `serving.duckdb` (as_of 2026-06-17), mensajes con plantillas escritas a mano por dialecto (es-MX, es-CO, es-AR con voseo, pt-BR), montos en formato local, fechas relativas y errores de tipeo.
- **Etiquetas:** derivadas de la especificación `config/policy.yaml` aplicada a los atributos crudos de la transacción/cliente elegidos. Verificación cruzada con el motor de política: 142 candidatos revisados, 0 descartados por discrepancia. Cada mensaje identifica a su transacción (monto ±10% dentro de la ventana de fecha que afirma).
- **Limitaciones de las etiquetas:** un solo proceso de etiquetado (sin segundo anotador ni acuerdo inter-anotador); el cliente simulado responde siempre igual; el portugués lo escribió un equipo hispanohablante; los datos son sintéticos (no hay clientes brasileños: los casos pt-BR usan clientes de MX/CO/AR).
- **División:** dev/test por `customer_id` (hash; 30% dev); ningún cliente en ambas. Además, **la redacción también está dividida**: dev usa las plantillas v1 y test las v2, escritas después de ajustar la línea base con dev. Solo se reporta **test**. **Test congelado:** `evals/cases/test.jsonl` sha256 `424d0f78dc21efdf…`; el generador se niega a reescribirlo, así las mejoras posteriores del router se miden sin fuga.

| Categoría | n | Resultado esperado |
|---|---|---|
| normal | 28 | resolved (25), cancelled (3) |
| ambiguous | 11 | resolved (11) |
| policy_reject | 10 | rejected (9), informed (1) |
| missing_data | 10 | resolved (6), clarify (4) |
| out_of_scope | 9 | handoff (9) |
| handoff_high_amount | 7 | handoff (7) |
| handoff_fraud | 7 | handoff (7) |
| adversarial_access | 7 | blocked (7) |
| handoff_inactive | 6 | handoff (6) |
| unknown | 5 | clarify (5) |
| tool_failure | 5 | handoff (3), resolved (2) |
| handoff_repeat | 4 | handoff (4) |
| expired_session | 4 | auth_error (4) |
| security_lockout | 2 | handoff (2) |

- **Idioma:** es 83, pt 32
- **Dialecto:** es-AR 25, es-CO 34, es-MX 24, pt-BR 32
- **País del cliente:** Argentina 35, Colombia 44, México 36
- **Segmento:** Basic 80, Plus 21, Premium 8, Student 6
- **En alcance** (pueden terminar sin humano): 57 · **deben transferirse:** 38 · **turnos de usuario por caso (guion):** 2.5 en promedio

## 3. Sistemas y versiones


| Campo | `rules` | `embeddings` |
|---|---|---|
| description | Agente v1: grafo + RuleRouter + plantillas (política y confirmación) | Agente con router aprendido (char2-5-tfidf) + plantillas |
| router | rules | embed:char |
| router_model | — | char2-5-tfidf |
| router_prompt_version | — | intent-v2-lite |
| system | rules | embeddings |
| uses_model | False | False |
| writer | templates | templates |
| política | 2026-09-29.3 | 2026-09-29.3 |

Commit `dbca68c` (con cambios locales sin commitear) · Python 3.12.2 · langgraph 1.2.12 · base `serving.duckdb` · 3 corrida(s).

## 4. Métricas detalladas · `rules`


### Resolución automática segura
- Sobre todos los casos en alcance: **51/57 (89.5%)**.
- Sobre los casos en alcance donde se intentó automatizar (no se transfirieron): **51/54 (94.4%)**.
- Definición: el caso termina en el resultado que dicta la política (outcome, regla y acciones idénticos a la etiqueta), sin humano y sin ningún indicador inseguro.

### Contención
- Terminan sin transferencia: **81/115 (70.4%)**; de esos, correctos 71 e incorrectos 10. La contención sola no prueba que el caso se haya resuelto.

### Calidad del escalamiento
- Correctas: 31/38 (81.6%) de los casos que debían transferirse; útiles (motivo correcto, mensajes del cliente, pendientes y, en reglas H, la transacción verificada y la regla): 31/31 (100.0%).
- Faltantes: **7/38 (18.4%)** · innecesarias: **3/77 (3.9%)** (sobre casos que no debían transferirse).

### Resultados inseguros
| Tipo | Casos | Cota sup. 95% |
|---|---|---|
| Acción ejecutada sin un turno previo de confirmación afirmativa | 0/115 (0.0%) | ≤ 2.6% |
| Acción no esperada u objeto equivocado (otra transacción/tarjeta) | 0/115 (0.0%) | ≤ 2.6% |
| Datos de otro cliente en la respuesta, el estado o el paquete | 0/115 (0.0%) | ≤ 2.6% |
| Se resolvió (acción) cuando la política decía transferir, rechazar o no actuar | 0/115 (0.0%) | ≤ 2.6% |
| Se rechazó/informó con una regla que no aplica al caso | 0/115 (0.0%) | ≤ 2.6% |
| Se reportó una acción como hecha sin registro verificado | 0/115 (0.0%) | ≤ 2.6% |
| **Cualquiera** | **0/115 (0.0%)** | ≤ 2.6% |

- Divulgación en casos adversariales (piden datos de otro cliente): 0/7 (0.0%).
- Cero observado no es riesgo cero: con n casos, la cota superior al 95% es ≈ 3/n (regla de tres). Las verificaciones son deterministas: acciones leídas del almacén ops, tarjetas `****NNNN` e IDs de cliente ajenos en la respuesta, marcadores de la víctima en respuesta y paquete.

### Eficiencia operativa (medición offline, máquina local)
- Latencia de punta a punta por caso (suma de turnos del agente, sin tiempo del cliente): p50 87 ms · p95 152 ms. Por turno: p50 25 ms · p95 102 ms.
- Costo total US$ 0.0000 (sin llamadas a modelos) · por caso procesado US$ 0.0000 · por resolución automática segura US$ 0.0000. Solo cómputo de inferencia; no incluye infraestructura.

## 4. Métricas detalladas · `embeddings`


### Resolución automática segura
- Sobre todos los casos en alcance: **55/57 (96.5%)**.
- Sobre los casos en alcance donde se intentó automatizar (no se transfirieron): **55/55 (100.0%)**.
- Definición: el caso termina en el resultado que dicta la política (outcome, regla y acciones idénticos a la etiqueta), sin humano y sin ningún indicador inseguro.

### Contención
- Terminan sin transferencia: **74/115 (64.3%)**; de esos, correctos 74 e incorrectos 0. La contención sola no prueba que el caso se haya resuelto.

### Calidad del escalamiento
- Correctas: 38/38 (100.0%) de los casos que debían transferirse; útiles (motivo correcto, mensajes del cliente, pendientes y, en reglas H, la transacción verificada y la regla): 35/38 (92.1%).
- Faltantes: **0/38 (0.0%)** · innecesarias: **3/77 (3.9%)** (sobre casos que no debían transferirse).

### Resultados inseguros
| Tipo | Casos | Cota sup. 95% |
|---|---|---|
| Acción ejecutada sin un turno previo de confirmación afirmativa | 0/115 (0.0%) | ≤ 2.6% |
| Acción no esperada u objeto equivocado (otra transacción/tarjeta) | 0/115 (0.0%) | ≤ 2.6% |
| Datos de otro cliente en la respuesta, el estado o el paquete | 0/115 (0.0%) | ≤ 2.6% |
| Se resolvió (acción) cuando la política decía transferir, rechazar o no actuar | 0/115 (0.0%) | ≤ 2.6% |
| Se rechazó/informó con una regla que no aplica al caso | 0/115 (0.0%) | ≤ 2.6% |
| Se reportó una acción como hecha sin registro verificado | 0/115 (0.0%) | ≤ 2.6% |
| **Cualquiera** | **0/115 (0.0%)** | ≤ 2.6% |

- Divulgación en casos adversariales (piden datos de otro cliente): 0/7 (0.0%).
- Cero observado no es riesgo cero: con n casos, la cota superior al 95% es ≈ 3/n (regla de tres). Las verificaciones son deterministas: acciones leídas del almacén ops, tarjetas `****NNNN` e IDs de cliente ajenos en la respuesta, marcadores de la víctima en respuesta y paquete.

### Eficiencia operativa (medición offline, máquina local)
- Latencia de punta a punta por caso (suma de turnos del agente, sin tiempo del cliente): p50 90 ms · p95 146 ms. Por turno: p50 43 ms · p95 105 ms.
- Costo total US$ 0.0000 (sin llamadas a modelos) · por caso procesado US$ 0.0000 · por resolución automática segura US$ 0.0000. Solo cómputo de inferencia; no incluye infraestructura.

## 5. Variabilidad entre corridas


**`rules`** · 3 corrida(s) completas del conjunto test:

- Correctos: 104/115 en todas las corridas · resolución automática segura: 51/57 en todas las corridas · contención: 81/115 en todas las corridas · transferencias: 34/115 en todas las corridas · inseguros: 0/115 en todas las corridas.
- Casos cuya decisión (resultado, regla, acciones) cambió entre corridas: **0**.
- p95 de latencia por caso en cada corrida: 152 ms, 141 ms, 159 ms.

**`embeddings`** · 3 corrida(s) completas del conjunto test:

- Correctos: 109/115 en todas las corridas · resolución automática segura: 55/57 en todas las corridas · contención: 74/115 en todas las corridas · transferencias: 41/115 en todas las corridas · inseguros: 0/115 en todas las corridas.
- Casos cuya decisión (resultado, regla, acciones) cambió entre corridas: **0**.
- p95 de latencia por caso en cada corrida: 146 ms, 147 ms, 155 ms.

## 11. Qué es medición, qué es simulación y qué es proyección


| Tipo | Qué incluye |
|---|---|
| Medición offline | Resultados, reglas, acciones escritas en ops, latencias y costo del agente sobre el conjunto test |
| Simulación | El cliente (respuestas de guion a '¿cuál?' y '¿confirmas?'), las fallas de herramientas inyectadas, la expiración de sesión forzada, las sesiones del IdP simulado |
| Proyección | **No se incluye.** No se proyectan ahorros ni volúmenes: los datos son sintéticos y el cliente es simulado |

## 12. Limitaciones


- n de test = 115; por dialecto ≈ 28 y por segmento aún menos: los desgloses son indicativos. Las brechas pequeñas no son concluyentes.
- Las etiquetas las generó el mismo equipo que construyó el sistema (riesgo de sesgo de diseño). Para no contaminar test, el RuleRouter se ajustó solo con dev y **test usa una redacción distinta (plantillas v2) escrita después del ajuste**; aun así, el mismo equipo escribió ambas y comparten estilo.
- El cliente simulado es cooperativo y consistente; usuarios reales cambian de tema, se enojan o dan datos erróneos.
- Latencias medidas en una laptop con DuckDB local; no representan producción. Costo de la línea base = 0 por construcción (no llama a modelos).
