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

