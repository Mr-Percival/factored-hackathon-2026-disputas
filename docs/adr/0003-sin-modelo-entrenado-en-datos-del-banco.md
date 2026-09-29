# 0003 · No entrenar sobre los textos del dataset; el componente aprendido se evalúa con etiquetas válidas

- **Estado:** aceptada
- **Fecha:** 2026-09-28

## Contexto
El reto pide evaluar al menos un componente aprendido contra una línea base, con etiquetas válidas y sin fuga. El EDA muestra que:
- `call_transcripts` tiene solo 42 textos de cliente distintos, y el texto no depende de la categoría.
- `detected_intents` = `consulta_general` en el 100% de los casos.
- `contact_reason` repite `reason_category`.
- Las descripciones de quejas son plantillas.

Un clasificador entrenado con eso tendría etiquetas inválidas.

## Decisión
No entrenamos sobre esos textos. El componente aprendido se evalúa donde sí hay etiquetas válidas:
1. **Detección de inyección de prompts:** un clasificador preentrenado contra la línea base de patrones (`guard.py`), evaluado sobre la división de prueba de datasets públicos etiquetados, con una muestra traducida al portugués marcada como generada por el equipo.
2. *(Opcional)* Router con LLM contra `RuleRouter`, sobre un conjunto conversacional generado y etiquetado por el equipo y declarado como tal.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Clasificar intención con las transcripciones | Usa el dataset | Etiquetas inválidas: la evaluación no significaría nada |
| Modelo de fraude con `is_fraud` | Etiqueta real | Solo `fraud_score` tiene señal (AUC ≈ 0.85); el resto de las variables son planas. Se usa como **regla** con umbral calibrado, no como modelo |
| **Inyección con datasets públicos** | Etiquetas válidas, splits existentes, refuerza seguridad | Cobertura de portugués limitada (se reporta) |

## Consecuencias
La limitación del dataset se documenta como hallazgo en lugar de esconderse. Los datos del banco alimentan la política, las herramientas y la línea base operativa.
