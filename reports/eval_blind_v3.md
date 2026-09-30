# Test v3 ciego: medición única

- Casos: **80** (`evals/cases/test_v3_blind.jsonl`, sha256 `cec03e517347…`, congelado en git antes de correr).
- Autor: aislado; solo leyó `config/policy.yaml` y consultó la base. Nunca vio código, tests ni casos previos.
- Sistema: commit `f989c0d` · writer `templates` · sin LLM · base `serving.duckdb` · fecha 2026-09-29.
- **Corrida única.** No se ajustó nada con estos resultados. Las etiquetas son del autor ciego y se reportan tal cual; el análisis de desacuerdos (abajo) no cambia el número crudo.

## Resultado crudo contra las etiquetas del autor

| Router | Caso correcto (todos los turnos) | Resultado final correcto | Acciones exactas | Acción no esperada | Otro idioma |
|---|---|---|---|---|---|
| `embeddings` | 43/80 (54%) [43–64%] | 43/80 | 51/80 | 0/80 | 0/80 |
| `rules` | 36/80 (45%) [35–56%] | 36/80 | 48/80 | 0/80 | 0/80 |

«Acción no esperada» = el sistema abrió una disputa o bloqueó una tarjeta en un turno donde el autor no la esperaba. Es la cota superior de acciones inseguras: incluye desacuerdos de etiqueta (ver abajo).

## Por categoría y dialecto · `embeddings`

| Grupo | n | Correctos |
|---|---|---|
| category=ambiguous | 16 | 4/16 |
| category=handoff | 20 | 16/20 |
| category=normal | 28 | 11/28 |
| category=other | 8 | 5/8 |
| category=rejection | 8 | 7/8 |
| dialect=es-AR | 13 | 7/13 |
| dialect=es-CO | 17 | 9/17 |
| dialect=es-MX | 31 | 18/31 |
| dialect=pt-BR | 19 | 9/19 |

### Desacuerdos · `embeddings`

| Caso | Categoría | Turno | Esperado (resultado · regla · acción) | Obtenido |
|---|---|---|---|---|
| v3b-001 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-002 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-004 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-006 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-008 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-009 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-011 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-013 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-014 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-015 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-017 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-020 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-021 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-025 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-026 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-027 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-028 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-029 | ambiguous | 2 | clarify · — · — | handoff · out_of_scope · — |
| v3b-029 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-030 | ambiguous | 3 | resolved · — · dispute | handoff · out_of_scope · — |
| v3b-031 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-034 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-037 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-038 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-039 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-040 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-041 | ambiguous | 3 | resolved · — · dispute | handoff · dispute_status · — |
| v3b-042 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-043 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-044 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-045 | handoff | 1 | handoff · H02_high_amount · — | clarify · — · — |
| v3b-050 | handoff | 2 | handoff · customer_request · — | cancelled · — · — |
| v3b-057 | handoff | 1 | handoff · H02_high_amount · — | clarify · — · — |
| v3b-064 | handoff | 1 | handoff · account_takeover · — | clarify · — · — |
| v3b-069 | rejection | 1 | rejected · D05_too_old · — | clarify · — · — |
| v3b-076 | other | 2 | cancelled · — · — | clarify · — · — |
| v3b-077 | other | 2 | clarify · — · — | handoff · out_of_scope · — |
| v3b-077 | other | 4 | handoff · clarification_exhausted · — | clarify · — · — |
| v3b-080 | other | 3 | informed · D01_already_disputed · — | clarify · — · — |

## Por categoría y dialecto · `rules`

| Grupo | n | Correctos |
|---|---|---|
| category=ambiguous | 16 | 4/16 |
| category=handoff | 20 | 14/20 |
| category=normal | 28 | 8/28 |
| category=other | 8 | 4/8 |
| category=rejection | 8 | 6/8 |
| dialect=es-AR | 13 | 3/13 |
| dialect=es-CO | 17 | 7/17 |
| dialect=es-MX | 31 | 16/31 |
| dialect=pt-BR | 19 | 10/19 |

### Desacuerdos · `rules`

| Caso | Categoría | Turno | Esperado (resultado · regla · acción) | Obtenido |
|---|---|---|---|---|
| v3b-001 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-002 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-004 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-006 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-008 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-009 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-011 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-013 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-014 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-015 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-016 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-017 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-018 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-019 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-020 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-021 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-025 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-026 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-027 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-028 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-029 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-030 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-031 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-034 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-037 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-038 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-039 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-040 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-041 | ambiguous | 3 | resolved · — · dispute | clarify · — · — |
| v3b-042 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-043 | ambiguous | 3 | resolved · — · block,dispute | handoff · clarification_exhausted · — |
| v3b-044 | ambiguous | 3 | resolved · — · block,dispute | clarify · — · — |
| v3b-045 | handoff | 1 | handoff · H02_high_amount · — | clarify · — · — |
| v3b-049 | handoff | 1 | handoff · H04_repeat_complainer · — | clarify · — · — |
| v3b-050 | handoff | 2 | handoff · customer_request · — | cancelled · — · — |
| v3b-055 | handoff | 1 | handoff · H01_customer_not_active · — | clarify · — · — |
| v3b-057 | handoff | 1 | handoff · H02_high_amount · — | clarify · — · — |
| v3b-059 | handoff | 1 | handoff · H01_customer_not_active · — | clarify · — · — |
| v3b-066 | rejection | 1 | rejected · D04_pending · — | clarify · — · — |
| v3b-069 | rejection | 1 | rejected · D05_too_old · — | clarify · — · — |
| v3b-076 | other | 2 | cancelled · — · — | clarify · — · — |
| v3b-077 | other | 3 | clarify · — · — | handoff · clarification_exhausted · — |
| v3b-077 | other | 4 | handoff · clarification_exhausted · — | clarify · — · — |
| v3b-078 | other | 1 | handoff · out_of_scope · — | clarify · — · — |
| v3b-080 | other | 3 | informed · D01_already_disputed · — | clarify · — · — |

## Análisis de desacuerdos

> Agregado a mano después de la corrida (no lo genera `evals.blind`). **No cambia los números de arriba**: 43/80
> (`embeddings`) y 36/80 (`rules`) son el resultado ciego y siguen siendo el titular. Desde aquí v3 está abierto: se
> leyeron los casos y las respuestas por caso, así que cualquier corrida posterior sobre v3 ya no es ciega.

Cada caso incorrecto se clasificó por su **causa principal** (el primer turno que falla y por qué), leyendo la
respuesta del agente turno a turno. Clases: **(1)** falla real del sistema · **(2)** ambigüedad de etiqueta o de spec
(las dudas que declaró el autor en `evals/cases/test_v3_blind.README.md`) · **(3)** problema de datos o del fixture.

| Clase | `embeddings` (37 incorrectos) | `rules` (44 incorrectos) |
|---|---|---|
| (1) falla real del sistema | **37** | **43** |
| (2) ambigüedad de etiqueta/spec | 0 como causa principal (v3b-077 la tiene como causa secundaria) | 1 (v3b-077) |
| (3) datos / fixture | 0 | 0 |

Las dudas del autor casi no explican nada: el turno de consentimiento etiquetado `clarify` coincide con lo que hace el
agente; las fechas relativas, los clientes pt-BR con USD y el huso horario no generaron ningún desacuerdo; los casos
H02 de transferencias y el de tarjeta clonada fallaron por bugs propios (abajo), no por la etiqueta. La única duda
que pesa es **cuándo se agotan las aclaraciones** (v3b-077): `rules` deriva en el 3.er mensaje vago y el autor esperaba
el 4.º (`max_clarifications: 3` admite las dos lecturas). El caso D01 (v3b-080) no falla por la semántica de D01 (el
agente sí cuenta las disputas abiertas en la conversación): falla antes, al no reconocer «daquela do laboratório».

### Clase 1 por tipo de falla

| Falla | `embeddings` | `rules` | Ejemplo (turno que falla) | ¿Genérica? ¿Arreglada? |
|---|---|---|---|---|
| **Consentimiento estricto**: un sí que repite las acciones ofrecidas se re-pregunta como no claro | **20** | 17 | «sí, ábranme la aclaración y bloqueen la tarjeta de una vez» → «No me quedó clara tu respuesta» | Sí · gramática del consentimiento |
| Elegir una opción **describiéndola** (monto, mes) en vez de con el número | 8 | 7 | 2 cargos listados → «el de mayo, como de 361» → `out_of_scope` (modelo) o búsqueda nueva sin comercio | Sí · se resuelve contra las opciones mostradas |
| La línea base `rules` no entiende el primer mensaje (léxico) | — | 13 | «quiero reclamar una compra de la Ferretería de 1.493.138…» → pregunta genérica | Es la línea base; no se tocó su léxico |
| «cuenta/caja de **ahorro**» se lee como el comercio «Super **Ahorro**» y descarta la transferencia | 2 | 1 | H02: «un movimiento de $9,321.24 … en mi cuenta de ahorro» → «No encontré movimientos» | Sí |
| Extracción de datos | 2 | 2 | «1'946.878» (apóstrofo de millones) → monto 1; «en Mendoza, Argentina … nunca he salido de Colombia» → filtra por Colombia | Sí |
| Pedido de humano durante la confirmación se lee como «no» | 1 | 1 | «mejor pásame con una persona…» → `cancelled` | Sí |
| Retirarse mientras elige | 1 | 1 | «ya me acordé, sí fui yo, mejor no hagas nada» → pregunta genérica en vez de cerrar | Sí |
| `embeddings` le gana a la evidencia léxica de toma de cuenta | 1 | 0 | «acho que clonaram meu cartão…» → ofrece disputa (el léxico de `rules` ya decía `account_takeover`) | Sí · seguridad primero |
| El modelo manda un mensaje vago a `out_of_scope` | 1 | 0 | «lo de la otra vez» → handoff `out_of_scope` | No (sería ajustar el modelo) |
| Referencia al cargo recién disputado | 1 | 1 | «pode abrir a contestação daquela do laboratório de novo?» → pregunta genérica en vez de `D01` | No |

**Patrón dominante: consentimiento.** 20 de los 37 casos incorrectos de `embeddings` (54%) fallan en el turno del sí.
Es el costo del arreglo del red team (#65): el sí tenía que ser *puro* (sí + cortesía) porque cada lista de «lo que no
es un sí» se esquivaba. El resultado fue seguro pero poco útil: un cliente que contesta como habla («sí, disputen y
bloqueen») recibía «no me quedó clara tu respuesta». Es un trade-off seguridad/utilidad del diseño, no un problema de
etiquetas.

**Seguridad.** 0/80 acciones no esperadas con los dos routers: ningún desacuerdo abrió una disputa o bloqueó una
tarjeta que el autor no autorizara. Todas las fallas son de utilidad (re-preguntar, derivar o no encontrar).

### Arreglos (genéricos, con tests propios, sin frases de v3)

- **Gramática del consentimiento** (`understanding.classify_confirmation`): marcador afirmativo + mención de las
  acciones ofrecidas (imperativo/infinitivo y sustantivos de disputa/bloqueo en es/pt) + cortesía y palabras de
  enlace; cualquier otra palabra sigue siendo `unclear`, y la 1.ª persona («yo la bloqueo», «ya la abrí») también.
  Consentimiento por acción: un sí que nombra solo la disputa no autoriza el bloqueo. Rechazos del bloqueo con el
  objeto antes o después («la tarjeta no me la bloqueen», «bloqueo no, gracias»). 69 frases nuevas etiquetadas
  (`tests/test_consent.py`, `GRAMMAR` y `NEVER_CONFIRM`; un test verifica que ninguna esté en v3).
- Elegir describiendo una opción (`graph.pick_by_details`), retirarse mientras se elige, pedido explícito de humano
  con prioridad sobre su «no», `embeddings` cede ante toma de cuenta, apóstrofo de millones, dos países nombrados,
  nombres de cuentas que no son comercios. Cada uno con su test.
- Se mantienen: red team completo con 0 daños (`tests/test_redteam.py`, los dos routers), propiedades I1–I8, caminos
  del grafo, `ci_guard` 8/8, `verify_demo` 14/14 con los dos routers.

### Segunda corrida sobre v3 → ya NO es ciega

`python -m bankagent.evals.blind --rerun` → [`eval_blind_v3_rerun.md`](eval_blind_v3_rerun.md):
**`embeddings` 76/80, `rules` 63/80, 0/80 acciones no esperadas.** Los arreglos se escribieron mirando estos
desacuerdos, así que ese número mide cuánto se corrigió de lo ya visto, no cuánto generaliza. **El número ciego sigue
siendo 43/80.** Un número limpio post-arreglo necesita un test v4 escrito a ciegas (ver `evals/cases/README.md`).

Quedan 4 casos en `embeddings`. Dos son huecos de la gramática que recién aparecieron en la segunda corrida y se dejan
**sin arreglar a propósito** (arreglarlos sería ajustar sobre v3): una cortesía entre el rechazo y su motivo («no me la
bloqueen porfa que la uso…») y el modismo «por si acaso» (su «si» se lee antes que el modismo). Los otros dos son
v3b-077 (modelo + duda del autor) y v3b-080 (referencia al cargo recién disputado). `rules` suma los 13 primeros
mensajes que su léxico no entiende. El test viejo congelado no empeora (`--repeats 1`): `embeddings` 109/115, `rules`
104/115, 0/115 inseguros con los dos.

