# Test v3: segunda corrida (ya no es ciega)

- Casos: **80** (`evals/cases/test_v3_blind.jsonl`, sha256 `cec03e517347…`, congelado en git antes de correr).
- Autor: aislado; solo leyó `config/policy.yaml` y consultó la base. Nunca vio código, tests ni casos previos.
- Sistema: commit `4258c37` · writer `templates` · sin LLM · base `serving.duckdb` · fecha 2026-09-29.
- **Segunda corrida sobre v3, tras arreglos informados por el análisis de v3 → ya NO es ciega.** Los arreglos se escribieron mirando los desacuerdos de la primera corrida, así que este número mide cuánto se corrigió de lo ya visto, no la generalización. El número ciego sigue siendo el de la primera corrida (`reports/eval_blind_v3.md`); un número limpio post-arreglo necesita un test v4 nuevo.

## Resultado crudo contra las etiquetas del autor

| Router | Caso correcto (todos los turnos) | Resultado final correcto | Acciones exactas | Acción no esperada | Otro idioma |
|---|---|---|---|---|---|
| `embeddings` | 76/80 (95%) [88–98%] | 76/80 | 78/80 | 0/80 | 0/80 |
| `rules` | 63/80 (79%) [69–86%] | 63/80 | 71/80 | 0/80 | 0/80 |

«Acción no esperada» = el sistema abrió una disputa o bloqueó una tarjeta en un turno donde el autor no la esperaba. Es la cota superior de acciones inseguras: incluye desacuerdos de etiqueta (ver abajo).

## Por categoría y dialecto · `embeddings`

| Grupo | n | Correctos |
|---|---|---|
| category=ambiguous | 16 | 16/16 |
| category=handoff | 20 | 20/20 |
| category=normal | 28 | 26/28 |
| category=other | 8 | 6/8 |
| category=rejection | 8 | 8/8 |
| dialect=es-AR | 13 | 13/13 |
| dialect=es-CO | 17 | 15/17 |
| dialect=es-MX | 31 | 30/31 |
| dialect=pt-BR | 19 | 18/19 |

### Desacuerdos · `embeddings`

| Caso | Categoría | Turno | Esperado (resultado · regla · acción) | Obtenido |
|---|---|---|---|---|
| v3b-002 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-015 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-077 | other | 2 | clarify · — · — | handoff · out_of_scope · — |
| v3b-077 | other | 4 | handoff · clarification_exhausted · — | clarify · — · — |
| v3b-080 | other | 3 | informed · D01_already_disputed · — | clarify · — · — |

## Por categoría y dialecto · `rules`

| Grupo | n | Correctos |
|---|---|---|
| category=ambiguous | 16 | 15/16 |
| category=handoff | 20 | 16/20 |
| category=normal | 28 | 20/28 |
| category=other | 8 | 5/8 |
| category=rejection | 8 | 7/8 |
| dialect=es-AR | 13 | 7/13 |
| dialect=es-CO | 17 | 12/17 |
| dialect=es-MX | 31 | 27/31 |
| dialect=pt-BR | 19 | 17/19 |

### Desacuerdos · `rules`

| Caso | Categoría | Turno | Esperado (resultado · regla · acción) | Obtenido |
|---|---|---|---|---|
| v3b-002 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-009 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-013 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-015 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-016 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-018 | normal | 2 | resolved · — · dispute | clarify · — · — |
| v3b-019 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-020 | normal | 2 | resolved · — · block,dispute | clarify · — · — |
| v3b-043 | ambiguous | 3 | resolved · — · block,dispute | handoff · clarification_exhausted · — |
| v3b-049 | handoff | 1 | handoff · H04_repeat_complainer · — | clarify · — · — |
| v3b-055 | handoff | 1 | handoff · H01_customer_not_active · — | clarify · — · — |
| v3b-057 | handoff | 1 | handoff · H02_high_amount · — | clarify · — · — |
| v3b-059 | handoff | 1 | handoff · H01_customer_not_active · — | clarify · — · — |
| v3b-066 | rejection | 1 | rejected · D04_pending · — | clarify · — · — |
| v3b-077 | other | 3 | clarify · — · — | handoff · clarification_exhausted · — |
| v3b-077 | other | 4 | handoff · clarification_exhausted · — | clarify · — · — |
| v3b-078 | other | 1 | handoff · out_of_scope · — | clarify · — · — |
| v3b-080 | other | 3 | informed · D01_already_disputed · — | clarify · — · — |

