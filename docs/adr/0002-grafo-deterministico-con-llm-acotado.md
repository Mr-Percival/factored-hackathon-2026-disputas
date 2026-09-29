# 0002 · Grafo determinista con el LLM acotado a interpretar y redactar

- **Estado:** aceptada
- **Fecha:** 2026-09-28

## Contexto
El reto exige aplicar permisos y política fuera del texto generado por el modelo, reportar solo acciones verificadas y justificar dónde usar IA y dónde lógica determinista.

## Decisión
Un solo agente en **LangGraph** con nodos explícitos (`guard → understand → find → decide → act/handoff → respond`).
- El modelo solo aparece detrás de dos interfaces: `Router` (intención + datos) y `Writer` (redacción).
- Las herramientas, la política y la verificación de acciones son código.
- Cada interfaz tiene una implementación sin modelo (reglas y plantillas) que sirve como **línea base** y como **camino alternativo** si el modelo falla.

## Alternativas consideradas
| Opción | A favor | En contra |
|---|---|---|
| Agente ReAct con acceso libre a herramientas | Rápido de armar | Permisos y política quedan en el prompt; difícil de auditar |
| Varios agentes | Llamativo | Más superficie de fallo; el reto dice que no es obligatorio |
| **Grafo con transiciones declaradas** | Auditable, testeable, el diagrama sale del código | Menos "flexible" ante pedidos fuera del flujo, que igual pasan a un humano |

## Consecuencias
El sistema funciona completo sin LLM, y los tests corren sin API keys. La mejora del LLM se mide contra la línea base sobre los mismos casos.
