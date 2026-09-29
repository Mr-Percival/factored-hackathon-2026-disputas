# Caminos del grafo (generado)

> Generado por `python -m bankagent.graph_check --write` desde `graph.EDGES`. No editar a mano:
> `tests/test_graph_paths.py` falla si este archivo no coincide con el grafo.

- Nodos: 10 · aristas: 24 · caminos START→END: 16 · largo máximo: 6 nodos
- Acíclico: sí
- Predecesores de `act`: understand
- Nodos inalcanzables desde START: ninguno
- Nodos que no llegan a END: ninguno
- Caminos que pasan por `act`: 2 · nodo inmediatamente anterior: understand

| # | Camino |
|---|---|
| 1 | START → guard → understand → find_transaction → decide → respond → END |
| 2 | START → guard → understand → find_transaction → decide → handoff → respond → END |
| 3 | START → guard → understand → find_transaction → respond → END |
| 4 | START → guard → understand → find_transaction → handoff → respond → END |
| 5 | START → guard → understand → find_card → respond → END |
| 6 | START → guard → understand → find_card → handoff → respond → END |
| 7 | START → guard → understand → select_option → decide → respond → END |
| 8 | START → guard → understand → select_option → decide → handoff → respond → END |
| 9 | START → guard → understand → select_option → respond → END |
| 10 | START → guard → understand → act → respond → END |
| 11 | START → guard → understand → act → handoff → respond → END |
| 12 | START → guard → understand → cancel → respond → END |
| 13 | START → guard → understand → handoff → respond → END |
| 14 | START → guard → understand → respond → END |
| 15 | START → guard → respond → END |
| 16 | START → guard → handoff → respond → END |
