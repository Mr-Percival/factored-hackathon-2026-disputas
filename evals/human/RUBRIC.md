# Evaluación humana de paquetes de handoff: rúbrica e instrucciones

**Tiempo:** unos 25 minutos por persona (35 paquetes, ≈ 45 s cada uno). **Evaluadores:** A, B, C y D, uno por persona del equipo.

Te pones en el lugar del **asesor humano** que recibe la derivación del agente. No evalúas si el agente hizo bien en
derivar: evalúas si **con este paquete puedes atender el caso sin volver a preguntarle nada al cliente**.

## Instrucciones

1. Abre tu archivo de lectura: `evals/human/bundles/rater_<X>.md` (en GitHub se ve formateado). Trae los paquetes
   **en tu orden**, que es distinto para cada evaluador.
2. Abre tu planilla `evals/human/sheets/rater_<X>.csv` (Excel, Sheets o un editor de texto). Cada fila ya tiene
   `orden` y `packet_id`, en el mismo orden del archivo de lectura.
3. Por cada paquete completa las columnas `a_pedido`, `b_hechos`, `c_motivo` y `d_preguntas` con un número del 1 al 5,
   `e_falta_critico` con `si` o `no` y, si pusiste `si`, `e_que_falta` con una frase corta.
4. **No abras `evals/human/_key/`** ni compares notas con el resto hasta que todos terminen. Algunos paquetes pueden
   estar incompletos o tener errores: califica lo que ves.
5. No vuelvas a leer paquetes anteriores ni corrijas notas ya puestas. La primera impresión es el dato.
6. Al terminar, guarda la planilla como CSV (UTF-8) con el mismo nombre y súbela en un commit
   (`git add evals/human/sheets/rater_<X>.csv`) o envíasela a quien corre el `score`.

Después, quien consolida corre:

```bash
PYTHONPATH=src python -m bankagent.evals.human_kit score "evals/human/sheets/*.csv"   # -> reports/human_eval.md
```

## Ítems

Los ítems (a) a (d) usan una escala de 1 a 5. Los anclajes definen 1, 3 y 5; el 2 y el 4 quedan entre medio.

### (a) `a_pedido`: ¿Entiendo qué pide el cliente sin volver a preguntar?
| Nota | Anclaje | Ejemplo |
|---|---|---|
| 5 | Queda claro qué cargo es (monto, fecha o comercio) y qué quiere el cliente (disputar, bloquear, otra cosa). | "No reconozco un cargo de 2.155.000 pesos del 17/06" |
| 3 | Se entiende el tipo de pedido, pero para actuar tendría que confirmar algún detalle con el cliente. | "Me cobraron algo raro", aunque después eligió una opción |
| 1 | No hay mensajes del cliente o no se puede saber qué quiere. | `_(sin mensajes)_` |

### (b) `b_hechos`: ¿Los hechos verificados son suficientes y correctos para decidir?
| Nota | Anclaje | Ejemplo |
|---|---|---|
| 5 | Transacción identificada (ID, fecha, monto, estado, comercio o canal) y datos del cliente (estado, segmento, reclamos), coherentes con el motivo. | H02 con 2,154,962.73 ARS: el monto supera el umbral |
| 3 | Faltan datos, pero puedo decidir con una sola consulta. O el paquete avisa con honestidad que no pudo verificar. | Falla técnica: está la transacción pero no los datos del cliente |
| 1 | No hay hechos o **contradicen** el motivo. | Dice "monto alto" y el monto es 12 USD; no hay transacción en una disputa |

Cuando el motivo no necesita transacción (fuera de alcance, bloqueo por seguridad, sin tarjeta), un paquete sin transacción puede sacar 4 o 5.

### (c) `c_motivo`: ¿Está claro por qué se derivó (regla)?
| Nota | Anclaje | Ejemplo |
|---|---|---|
| 5 | Motivo e ID de regla con su explicación, **consistentes con los hechos**. | `H04_repeat_complainer` y la fila "reclamante recurrente: sí" |
| 3 | Hay un motivo, pero tengo que deducir el porqué, o hay varias reglas y no queda claro cuál pesa. | `tool_failure` sin saber qué herramienta falló |
| 1 | No hay motivo o **no coincide** con los hechos. | Dice H04 (reclamante recurrente) y los hechos muestran 0 reclamos y "reclamante recurrente: no" |

### (d) `d_preguntas`: ¿Las preguntas abiertas son útiles y accionables?
| Nota | Anclaje | Ejemplo |
|---|---|---|
| 5 | Son específicas de este caso y me dicen el próximo paso. | "Coordinar con fraude: bloqueo de la tarjeta y revisión de otros movimientos" |
| 3 | Son correctas pero genéricas: servirían para cualquier caso. | "Validar con el cliente si reconoce al comercio." |
| 1 | No hay preguntas o no tienen relación con el caso. | `_(ninguna)_` |

### (e) `e_falta_critico`: ¿Falta algo crítico? (`si` / `no` + texto libre)
Pon `si` cuando falta algo **sin lo cual no podrías actuar**, o que te obligaría a abrir otro sistema o a volver a
contactar al cliente. En `e_que_falta` anota qué falta, en pocas palabras ("qué herramienta falló", "prioridad/SLA",
"monto no coincide con la regla"). Un dato "lindo de tener" no cuenta como crítico.

## Cómo se analiza (para quien consolida)

- Medias por ítem y por motivo de handoff, con IC 95% por bootstrap sobre paquetes. Los controles no entran en las medias.
- Acuerdo entre evaluadores: α de Krippendorff ordinal para (a)–(d) y κ de Fleiss / Cohen para (e). Con α ≥ 0.80 el
  acuerdo es fiable; entre 0.667 y 0.80, provisional; por debajo, revisar los anclajes antes de sacar conclusiones.
- Controles de atención: hay algunos paquetes degradados a propósito, definidos en la clave. Se cuentan como detectados
  cuando el ítem afectado recibe ≤ 2 o cuando se marcó (e). Si un evaluador detecta menos del 60%, se revisan sus notas.
- Contraste con el verificador determinista (`human_kit check`): si la mayoría de los evaluadores marca (e), se compara
  con la completitud automática del paquete.
