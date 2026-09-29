# 0004 · Router y writer con LLM: modelos, versiones, caminos alternativos y privacidad

- **Estado:** propuesta
- **Fecha:** 2026-09-28
- **Autor(es):** equipo (issues #6 y #7)

## Contexto
El [ADR 0002](0002-grafo-deterministico-con-llm-acotado.md) limita el modelo a dos interfaces: `Router`
(intención + idioma + slots) y `Writer` (redacción). Las líneas base (`RuleRouter`, `TemplateWriter`) ya
resuelven el flujo; el LLM debe **mejorar** comprensión y tono sin tocar permisos, política ni acciones, y
el reto pide: no enviar datos privados al proveedor, reportar versiones de modelo y prompt, reintentos
acotados, camino alternativo seguro y trade-offs explícitos entre autonomía, precisión, latencia y costo.
El proveedor de LLM del equipo todavía no es definitivo.

## Decisión
1. **Cliente agnóstico de proveedor** (`llm.py`): `LLMClient.complete_json(system, messages, schema, model)
   -> (dict, LLMUsage)`. Implementaciones: `AnthropicClient` (SDK oficial, salida estructurada con JSON
   schema, key desde `ANTHROPIC_API_KEY`, nunca registrada) y `FakeLLMClient` (tests). Otro proveedor = una
   clase nueva + una rama en `factory.make_llm_client`.
2. **LLMRouter** (`llm_router.py`, prompt `router-v1`): recibe solo el texto ya enmascarado, `today` y
   `awaiting`. La salida se valida **en código** (enums, tipos, rangos, fechas ISO no futuras y coherentes,
   `select_option` con número). `confirm`/`deny`/`select_option` sin una pregunta pendiente se degradan a
   `unknown`: el modelo no puede disparar `act` fuera de contexto.
3. **LLMWriter** (`llm_writer.py`, prompt `writer-v1`): recibe solo la plantilla ya armada, los hechos de esa
   respuesta y una pista de dialecto derivada del país del perfil (México→es-MX, Colombia→es-CO,
   Argentina→es-AR con voseo, `pt`→pt-BR, resto→es-419). Su salida pasa por `verify_reply`, determinista:
   - toda cifra, fecha, máscara de tarjeta (`****1234`) e ID (`DSP-…`, `T-…`, `CLI-…`) de la respuesta debe
     estar en los hechos o en la plantilla; y todas las de la plantilla deben seguir presentes (literal);
   - ninguna palabra de promesa (reembolso, abono, aprobado, garantía, plazos en horas/días…) que no esté
     en el texto fijo de la plantilla (las palabras que vienen de datos, como un comercio llamado
     "…REEMBOLSO", no cuentan como promesa);
   - si la plantilla pregunta, la respuesta también; sin números de tarjeta completos ni emails; largo
     máximo = 2× la plantilla + 120 caracteres.
   Los mensajes de sesión/seguridad (`session_*`, `forbidden`, `blocked_input`, `security_lockout`) **no se
   reescriben**: texto fijo auditado y cero costo. Las explicaciones de política siguen saliendo del id de
   regla (`rule_text` delega en la plantilla).
4. **Caminos alternativos** (nunca se cae el turno):
   | Falla | Router | Writer |
   |---|---|---|
   | Sin key / sin paquete | `rules(fallback:no_client)` | plantilla, `writer_fallback=no_client` |
   | Timeout (6 s) | reglas **sin reintento** (ya se gastó el presupuesto de latencia) | plantilla |
   | 429 / 5xx / conexión / JSON inválido / esquema | hasta **2 reintentos** y luego reglas | 1 reintento y luego plantilla |
   | Auth / 400 / rechazo del modelo | reglas, sin reintento | plantilla, sin reintento |
   | Verificación fallida | — | plantilla sin reintento; la traza guarda las violaciones |
5. **Trazabilidad**: cada llamada deja en la entrada de la traza del nodo (`understand` / `respond`) un campo
   `llm` con `provider`, `model`, `prompt_version`, `attempts`, `errors`, `fallback`, tokens de entrada y
   salida (incluye intentos descartados, que igual se pagan), `cost_usd` estimado con `llm.PRICES` y
   `latency_ms`. `understanding.router` dice qué router respondió realmente
   (`llm:claude-haiku-4-5-20251001@router-v1` o `rules(fallback:timeout)`). Cambiar un prompt obliga a
   subir `PROMPT_VERSION`, así la evaluación compara versiones.

### Modelo por componente
| Componente | Modelo por defecto | Por qué |
|---|---|---|
| Router | Claude Haiku 4.5 (`claude-haiku-4-5-20251001`) | Clasificación corta con esquema cerrado: no necesita razonamiento largo. Es el más barato (US$1 / US$5 por millón de tokens de entrada / salida) y el más rápido, y está en el camino crítico de cada turno. Soporta salida estructurada. Si falla, la línea base cubre. |
| Writer | Claude Haiku 4.5 | La tarea es parafrasear ~2 frases sin agregar datos; el verificador garantiza la fidelidad, así que el modelo solo aporta tono. Sonnet 5.5 (US$2 / US$10) queda como opción (`BANKAGENT_WRITER_MODEL`) si la evaluación muestra mejor dialecto que justifique el doble de costo y más latencia. |

Estimación (a confirmar con el harness de evaluación, #12): router ≈ 700 tokens de entrada / 60 de salida
≈ US$0.001 por turno; writer ≈ 600 / 100 ≈ US$0.001. Una disputa completa (3 turnos) cuesta menos de
US$0.01 y agrega dos llamadas en serie por turno (≈ 1–2 s con Haiku).

### Privacidad: qué sale hacia el proveedor
| Sale | No sale nunca |
|---|---|
| Texto del cliente **después** de `guard.redact` ([TARJETA], [EMAIL], [TELEFONO], [CURP]) | Nombre, documento, email, teléfono, `customer_id` |
| `today` y `awaiting` | Número de tarjeta completo (en la base ya está enmascarado; además se bloquea el envío si aparece un número de 13+ dígitos o un email) |
| Para el writer: el movimiento ya formateado (fecha · monto · comercio · país/ciudad), la tarjeta enmascarada, el número de caso, la explicación de la regla | IDs internos de transacción/producto, historial, puntaje de fraude, política |
| El dialecto (derivado del país en código) | El país en sí no se envía; ni el texto del cliente al writer |

`test_no_pii_reaches_the_provider` afirma esto sobre lo que captura el `FakeLLMClient`.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Router con tool use (`tool_choice` forzado) | Patrón conocido | Salida estructurada es más directa para "devuelve este JSON"; algunos modelos nuevos rechazan `tool_choice` forzado |
| Writer libre sin verificador | Más natural | Puede inventar montos, plazos o reembolsos; el reto penaliza reportar lo no verificado |
| Verificador con otro LLM (juez) | Detecta paráfrasis sutiles | Otra llamada (costo y latencia), no determinista, no auditable |
| Sonnet para todo | Mejor calidad potencial | 2× costo y más latencia en el camino crítico sin evidencia de ganancia; se decide con la evaluación |
| Reintentar también ante timeout | Más tasa de éxito del LLM | Duplica la latencia en el peor caso; la línea base ya responde bien |

## Consecuencias
- Autonomía: el modelo no gana ninguna; solo propone intención/slots y texto. Precisión: el router puede
  entender más variaciones que las reglas y el writer no puede degradar los hechos (en el peor caso, se usa
  la plantilla). Latencia y costo: dos llamadas por turno, medidas en la traza.
- El verificador es conservador: puede rechazar paráfrasis válidas (por ejemplo, "15 de junio" en lugar de
  "15/06/2026"). Se acepta: la plantilla es correcta; la tasa de `writer_fallback` se mide en la evaluación.
- Con más tiempo: caché de prompts cuando el system prompt supere el mínimo cacheable; streaming del writer
  para bajar la latencia percibida; ejemplos few-shot por dialecto evaluados contra hablantes; router con
  modelo de decisión propio (Jev) comparado contra Haiku; presupuesto de costo por conversación con corte
  automático a la línea base; un segundo proveedor detrás de `LLMClient` para resiliencia.
