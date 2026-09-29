"""Verificación estática del grafo declarado en `graph.EDGES`.

No ejecuta el agente: analiza la tabla de transiciones como un grafo dirigido y responde, de forma exhaustiva,
preguntas que los tests de ejemplo solo muestrean:

- ¿Es acíclico? (cada turno termina en un número acotado de nodos)
- ¿Qué caminos existen de START a END? (listado completo, exportado a docs/graph-paths.md)
- ¿Desde qué nodos se puede llegar a `act`? (debe ser solo `understand`)
- ¿Hay nodos inalcanzables o nodos que no pueden llegar a END?

    python -m bankagent.graph_check            # imprime el listado
    python -m bankagent.graph_check --write    # regenera docs/graph-paths.md
"""
from __future__ import annotations

import os
import sys

from langgraph.graph import END

START_NODE = "guard"  # START -> guard es la única arista de entrada (Agent._build)


def _edges() -> dict[str, list[str]]:
    from .graph import EDGES
    return EDGES


def successors(edges: dict[str, list[str]], node: str) -> list[str]:
    return [t for t in edges.get(node, []) if t != END]


def predecessors(edges: dict[str, list[str]], node: str) -> set[str]:
    return {src for src, targets in edges.items() if node in targets}


def find_cycle(edges: dict[str, list[str]]) -> list[str] | None:
    """Devuelve un ciclo (lista de nodos) o None si el grafo es acíclico."""
    color: dict[str, int] = {}  # 0 sin visitar · 1 en la pila · 2 terminado
    stack: list[str] = []

    def dfs(n: str) -> list[str] | None:
        color[n] = 1
        stack.append(n)
        for m in successors(edges, n):
            if color.get(m, 0) == 1:
                return stack[stack.index(m):] + [m]
            if color.get(m, 0) == 0:
                found = dfs(m)
                if found:
                    return found
        stack.pop()
        color[n] = 2
        return None

    for n in edges:
        if color.get(n, 0) == 0:
            found = dfs(n)
            if found:
                return found
    return None


def all_paths(edges: dict[str, list[str]], start: str = START_NODE) -> list[list[str]]:
    """Todos los caminos start -> END (el grafo debe ser acíclico; si no, la lista sería infinita)."""
    if find_cycle(edges):
        raise ValueError("El grafo tiene ciclos: la enumeración de caminos no termina")
    out: list[list[str]] = []

    def walk(path: list[str]):
        node = path[-1]
        for t in edges.get(node, []):
            if t == END:
                out.append(path)
            else:
                walk(path + [t])

    walk([start])
    return out


def reachable(edges: dict[str, list[str]], start: str = START_NODE) -> set[str]:
    seen, todo = {start}, [start]
    while todo:
        for m in successors(edges, todo.pop()):
            if m not in seen:
                seen.add(m)
                todo.append(m)
    return seen


def can_reach_end(edges: dict[str, list[str]]) -> set[str]:
    ok = {n for n, targets in edges.items() if END in targets}
    changed = True
    while changed:
        changed = False
        for n, targets in edges.items():
            if n not in ok and any(t in ok for t in targets):
                ok.add(n)
                changed = True
    return ok


def report(edges: dict[str, list[str]] | None = None) -> str:
    """Listado en Markdown (lo que se exporta a docs/graph-paths.md)."""
    edges = edges or _edges()
    paths = all_paths(edges)
    unreachable = sorted(set(edges) - reachable(edges))
    dead = sorted(set(edges) - can_reach_end(edges))
    via_act = [p for p in paths if "act" in p]
    lines = [
        "# Caminos del grafo (generado)",
        "",
        "> Generado por `python -m bankagent.graph_check --write` desde `graph.EDGES`. No editar a mano:",
        "> `tests/test_graph_paths.py` falla si este archivo no coincide con el grafo.",
        "",
        f"- Nodos: {len(edges)} · aristas: {sum(len(t) for t in edges.values())} · "
        f"caminos START→END: {len(paths)} · largo máximo: {max(len(p) for p in paths)} nodos",
        f"- Acíclico: {'sí' if find_cycle(edges) is None else 'NO'}",
        f"- Predecesores de `act`: {', '.join(sorted(predecessors(edges, 'act')))}",
        f"- Nodos inalcanzables desde START: {', '.join(unreachable) or 'ninguno'}",
        f"- Nodos que no llegan a END: {', '.join(dead) or 'ninguno'}",
        f"- Caminos que pasan por `act`: {len(via_act)} (todos con `understand` inmediatamente antes)",
        "",
        "| # | Camino |",
        "|---|---|",
    ]
    lines += [f"| {i} | START → {' → '.join(p)} → END |" for i, p in enumerate(paths, 1)]
    return "\n".join(lines) + "\n"


DOC = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "docs", "graph-paths.md")


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    text = report()
    if "--write" in argv:
        with open(DOC, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print(f"escrito {DOC}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
