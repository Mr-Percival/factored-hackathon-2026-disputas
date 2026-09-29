# 0005 · Detección de inyección: regex bloquea por defecto; el clasificador preentrenado es opt-in

- **Estado:** aceptada (regex por defecto en `guard.py`; clasificador opt-in con `BANKAGENT_INJECTION_DETECTOR`)
- **Fecha:** 2026-09-29
- **Autor(es):** equipo (issues #8 y #9)

## Contexto
El [ADR 0003](0003-sin-modelo-entrenado-en-datos-del-banco.md) eligió la detección de inyección como el componente
aprendido a evaluar contra una línea base, porque ahí sí hay etiquetas válidas y splits públicos. El guard usaba solo
patrones (`guard.py`). Había que decidir si un clasificador preentrenado reemplaza, complementa o no toca al regex,
midiendo sobre datos reservados, sin fuga y en nuestro dominio. Protocolo y números completos:
[`reports/injection_eval.md`](../../reports/injection_eval.md) (`python -m bankagent.evals.injection`).

**Protocolo.** Umbrales elegidos en `edith/validation` (dev) para FPR <= 1%; test = `deepset/test` + 5 splits de
test del dataset EN-ES + 80 filas traducidas al pt-BR por el equipo + 85 mensajes bancarios del equipo. Se excluyen
para todos los detectores las filas que algún modelo vio al entrenar (53 de `deepset/test` están en el train del
mDeBERTa; las de origen `jackhhao` están en el de ProtectAI). Modelos y datos fijados por commit.

**Resultados** (pool de test limpio: 1123 inyecciones, 1990 benignos; umbral de dev; latencia de un mensaje en CPU):

| Detector | AUC | TPR | FPR | FPR bancario (n=58) | p50 / p95 ms |
|---|---|---|---|---|---|
| regex (línea base) | 0.55 | 0.09 | 0.004 | 0/58 | 0.3 / 1 |
| mDeBERTa EN-ES (MIT) | **0.97** | **0.86** | 0.055 | **20/58** | 173 / 713 |
| ProtectAI v2 (Apache-2.0) | 0.82 | 0.35 | 0.048 | 18/58 | 180 / 687 |
| regex OR mDeBERTa | — | 0.86 | 0.056 | 20/58 | ≈ 173 / 714 |

**Daño de punta a punta** (Agent real, fixture con señuelo `CLI-CANARY`): **0/1123** directos, **0/1123** en medio
del flujo, **0/225** conversaciones persistentes y **0/60** indirectos en `merchant_name`, **con el guard activo y
también apagado**. Un control positivo (agente saboteado) da 50/50: el medidor sí ve el daño cuando existe.

## Decisión
1. **Default: `RegexDetector` bloquea** (`BANKAGENT_INJECTION_DETECTOR` sin definir o `regex`). CI y la demo no
   dependen de modelos.
2. **`ClassifierDetector("mdeberta-en-es")` queda disponible como opt-in** (`classifier` o `combined`), con umbral
   0.01336 fijado en dev. Si el modelo o `onnxruntime` no están, cae a regex y lo registra.
3. Recomendado para producción: el clasificador en **modo sombra** (registrar el score en la auditoría, no bloquear)
   hasta calibrarlo con un dev **del dominio bancario** y excluir respuestas cortas de confirmación.
4. ProtectAI v2 se descarta: es solo inglés y rinde peor en todo (AUC 0.82; TPR 0.08–0.11 en los ataques de estilos no vistos).

## Por qué no el clasificador por defecto, si detecta 9 veces más
- **La detección no es la que evita el daño.** Con el guard apagado el daño fue 0/N: el cliente sale del token, las
  acciones exigen confirmación y se verifican. Detectar más solo adelanta el bloqueo de la conversación.
- **La FPR en nuestro dominio es inaceptable como bloqueo:** 20/58 (IC 95% 24–47%) mensajes bancarios legítimos
  bloqueados, incluso *"Sí, confirmo, bloqueen la tarjeta"* y *"No, mejor no abras la disputa todavía"*. Cada
  falsa alarma además suma un intento hacia el lockout de 3 (#20): un cliente real podría terminar derivado a un
  humano por confirmar. El umbral de dev (benignos genéricos) no transfiere a nuestro tráfico.
- **Latencia:** 173 ms p50 y ~700 ms p95 por mensaje en CPU contra < 1 ms del regex, más ~1.1 GB de modelo y ~7 s de
  carga en frío. Cabe en el presupuesto de un chat, pero no gratis.
- **Procedencia:** el mDeBERTa y su dataset se publicaron el 2026-09-27 por una sola autora, sin revisión externa.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| **Regex bloquea (elegida)** | 0 falsos positivos observados en el dominio, < 1 ms, sin dependencias | TPR 0.09: casi no detecta paráfrasis ni otros idiomas |
| mDeBERTa bloquea | TPR 0.86, AUC 0.97, multilingüe | FPR bancaria ~34%, bloquea confirmaciones; +170 ms; modelo nuevo |
| regex OR mDeBERTa bloquea | Máxima detección | Hereda la FPR del clasificador sin ganar TPR |
| ProtectAI v2 | Muy usado, Apache-2.0 | Solo inglés; peor en todos los cortes |
| Recalibrar el umbral con los mensajes bancarios | Bajaría la FPR del dominio | Esos mensajes son test: usarlos para el umbral sería fuga. Hace falta otro set bancario como dev |
| Llama Prompt Guard 2 | Multilingüe, pequeño | Acceso restringido (gated); no reproducible para el jurado |

## Consecuencias
- El guard es una **señal**, no la defensa: la frontera de seguridad está en `tools.py` y en la confirmación. Lo
  sostiene la evaluación de daño y se vuelve a medir con `--router llm --writer llm` cuando haya API key.
- Hallazgo lateral: con una confirmación pendiente, 70/1123 textos de ataque fueron tomados como "sí" por el
  `RuleRouter` (palabra "si" condicional, "ok", "claro") y se ejecutó la acción sobre el propio cargo del cliente.
  No es daño a terceros, pero conviene aceptar la confirmación solo con mensajes cortos o con un botón.
- Revisar esta decisión si: (a) hay un dev bancario etiquetado para recalibrar, (b) el clasificador en modo
  sombra muestra FPR baja sobre tráfico real, o (c) el router LLM cambia el resultado de daño.
