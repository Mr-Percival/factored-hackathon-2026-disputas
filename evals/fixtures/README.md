# Fixtures de evaluación GENERADOS POR EL EQUIPO

No provienen del organizador ni de un dataset público revisado. Se usan solo como **test** (nunca para elegir umbrales).

## `pt_team_translation.jsonl` · traducción del equipo al pt-BR (80 filas, 40 inyección / 40 benignas)
- **Origen:** `edithngalame/prompt-injection-en-es` @ `bb574ea9`, split `test`, filas en inglés de <= 280 caracteres.
- **Muestreo:** estratificado por familia con semilla 2026: 27 `gandalf` + 13 `deepset_injection` (inyección);
  20 `dolly_instruction` + 14 `deepset_benign` + 6 `email_benign_insert` (benignas). Se excluyó `jackhhao`
  (está en el entrenamiento de ProtectAI).
- **Método:** traducción hecha por el equipo con asistencia de un LLM (Claude), fila a fila y sin revisión de
  un hablante nativo. Se conservan las etiquetas originales, incluso las dudosas de deepset.
- **Procedencia por fila:** `source`, `source_split`, `source_row` (índice en el parquet) y `source_sha1`
  (primeros 12 hex del SHA-1 del texto original).
- **Licencia:** heredan la de la fila original (Apache-2.0 para deepset, MIT para gandalf, CC-BY-SA-3.0 para dolly).

## `banking_domain.jsonl` · mensajes del dominio bancario (85 filas, es/pt)
- Escritos a mano por el equipo. `family`: `benign` (31), `tricky` (27, benignos con palabras como
  *ignorar*, *olvidar*, *reglas*, *administrador*) y `attack` (27, ataques contra este agente: señuelo
  `CLI-CANARY`, acciones sin confirmar, extracción de política).
- Sirven para medir falsos positivos en NUESTRO tráfico y como ataques del dominio en la evaluación de daño.
