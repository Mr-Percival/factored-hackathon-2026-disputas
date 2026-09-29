# 0001 · Flujo: disputa de cargos no reconocidos + bloqueo de tarjeta

- **Estado:** aceptada
- **Fecha:** 2026-09-28

## Contexto
El reto pide **un** flujo con profundidad. Según el EDA (`reports/EDA_findings.md`):
- Las quejas son el 17% de los contactos y tienen el peor FCR (43.6%), 63% de seguimiento y el doble de duración.
- En PQR, "Cargo no reconocido" y "Cobro indebido" son el 36% de los casos, con 20% de incumplimiento de SLA y una mediana de 16 días.

## Decisión
Automatizar el intake de la disputa: identificar la transacción, aplicar la política, abrir la disputa y bloquear la tarjeta **con confirmación**, y transferir a un humano con contexto completo cuando la política lo indique.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Elegibilidad de crédito | Tema de alto impacto | Exige separar conversación, riesgo y política; alto riesgo de error en 7 días |
| Consultas de cuenta | Más simple | Sin acciones ni handoff interesante que demostrar |
| **Disputas** | Datos que lo justifican, acciones seguras (sin mover dinero), los 3 casos exigidos aparecen de forma natural | Los textos del dataset no sirven para entrenar |

## Consecuencias
El caso normal, el ambiguo (varias transacciones posibles) y el de humano (monto alto, fraude, reclamante recurrente) salen del mismo flujo. No se mueve dinero.
