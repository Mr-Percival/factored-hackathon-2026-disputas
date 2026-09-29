# 0004 · Evaluación con casos generados por construcción, divididos por cliente y por redacción

- **Estado:** aceptada
- **Fecha:** 2026-09-28
- **Autor(es):** equipo (issues #12 y #13)

## Contexto
La rúbrica pide comparar la línea base con el sistema propuesto sobre la misma carga reservada. Hay que reportar la
mezcla de casos, la calidad de las etiquetas, las versiones, la variabilidad entre corridas, las fallas, las
resoluciones seguras, la contención, el escalamiento, los resultados inseguros y la eficiencia, y desglosar por
idioma y segmento. El dataset no trae conversaciones etiquetadas válidas (ADR 0003).

## Decisión
- Los casos se **generan de forma determinista** a partir de clientes y transacciones reales de `serving`. La etiqueta
  sale de `policy.yaml` aplicada a los atributos crudos y se verifica con el motor de política.
- El cliente es un **guion** (simulación): elige la opción correcta y responde la confirmación que dice la etiqueta.
- Los resultados inseguros se detectan con **reglas deterministas**: acciones leídas del almacén ops, marcadores de
  datos ajenos y resultados que contradicen la política.
- **División doble:** por `customer_id` (dev/test) y por **redacción** (plantillas v1 para dev, v2 para test, escritas
  después de ajustar). Solo se reporta test.
- Los sistemas se registran por nombre (`SYSTEMS` en `evals/runner.py`), así el router y el writer con LLM se
  comparan sobre los mismos casos con una línea.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Etiquetar a mano conversaciones libres | Más natural | Lento, sin garantía de que la etiqueta coincida con la política |
| Usar un LLM como juez | Escala | Etiquetas no deterministas ni auditables; mismo sesgo que el sistema evaluado |
| **Construcción + política como especificación** | Etiquetas verificables, reproducible con una semilla | Riesgo de sesgo de diseño; la redacción la escribió el mismo equipo |
| Split solo por cliente | Simple | Las plantillas se filtran de dev a test: el primer borrador infló test de 77 a 114 de 115 |

## Consecuencias
El número de test es honesto respecto del ajuste de la línea base, pero sigue siendo una simulación offline. Si se
agregan plantillas o se cambia la política, hay que regenerar los casos y los hashes quedan en `manifest.json`.
Conviene sumar un segundo anotador o conversaciones reales antes de sacar conclusiones fuertes.
