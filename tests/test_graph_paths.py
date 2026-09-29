"""Verificación estática del grafo (#31): se analiza `EDGES` completo, no una muestra de conversaciones.

1. Enumeración de todos los caminos START -> END (acíclico => cada turno termina en <= N nodos).
2. `act` solo es alcanzable desde `understand`.
3. El nodo `understand` devuelve `act` SOLO con una confirmación pendiente y fresca + intención `confirm`:
   se prueba EXHAUSTIVAMENTE sobre awaiting × intención × confianza × acción pendiente (fresca / vieja / ninguna).
4. Todo nodo es alcanzable y puede llegar a END; el listado exportado a docs/graph-paths.md está al día.
"""
import itertools

import pytest

from bankagent import graph_check as gc
from bankagent.graph import EDGES, Agent
from bankagent.policy import PolicyEngine
from bankagent.understanding import INTENTS, Slots, Understanding

END = "__end__"


def test_graph_is_acyclic_and_every_path_ends_in_respond():
    assert gc.find_cycle(EDGES) is None
    paths = gc.all_paths(EDGES)
    assert paths and all(p[0] == "guard" and p[-1] == "respond" for p in paths)
    assert max(len(p) for p in paths) <= len(EDGES)  # cota del trabajo por turno
    # cada par consecutivo de cada camino es una arista declarada
    assert all(b in EDGES[a] for p in paths for a, b in zip(p, p[1:]))


def test_act_is_only_reachable_from_understand():
    assert gc.predecessors(EDGES, "act") == {"understand"}
    for p in gc.all_paths(EDGES):
        if "act" in p:
            assert p[p.index("act") - 1] == "understand"
            assert p[:2] == ["guard", "understand"]  # y understand solo después de guard


def test_all_nodes_reachable_and_can_finish():
    assert gc.reachable(EDGES) == set(EDGES)
    assert gc.can_reach_end(EDGES) == set(EDGES)
    assert set(EDGES) - {n for p in gc.all_paths(EDGES) for n in p} == set()  # sin nodos huérfanos


def test_checker_detects_problems_it_claims_to_detect():
    """El verificador no es trivial: detecta un ciclo, un nodo inalcanzable y un nodo sin salida."""
    bad = {"guard": ["understand", "respond"], "understand": ["guard", "respond"], "respond": [END],
           "island": ["respond"], "sink": ["sink2"], "sink2": []}
    assert gc.find_cycle(bad)
    assert "island" not in gc.reachable(bad)
    assert {"sink", "sink2"}.isdisjoint(gc.can_reach_end(bad))
    with pytest.raises(ValueError):
        gc.all_paths(bad)


def test_exported_path_listing_is_up_to_date():
    with open(gc.DOC, encoding="utf-8") as f:
        assert f.read() == gc.report(), "docs/graph-paths.md desactualizado: python -m bankagent.graph_check --write"


# ------------------------------------------------------------------ enrutamiento de `understand`, exhaustivo
class StubRouter:
    name = "stub"

    def __init__(self):
        self.u: Understanding | None = None
        self.seen: list = []

    def understand(self, text, today, awaiting):
        self.seen.append((text, awaiting))
        return self.u


CONFIDENCES = [0.0, 0.2, 0.59, 0.6, 0.61, 0.85, 1.0]
AWAITING = [None, "option", "confirmation", "otro"]
PENDING = ["fresh", "stale", "none"]
TURN = 7


@pytest.fixture(scope="module")
def stub_agent(serving_db):
    from bankagent.identity import IdentityService
    from bankagent.tools import BankTools
    router = StubRouter()
    return Agent(BankTools(serving_db, IdentityService()), PolicyEngine(), router=router), router


def _expected(awaiting, intent, conf, pending):
    confirmable = awaiting == "confirmation" and pending == "fresh"
    if confirmable and intent == "confirm" and conf >= 0.6:  # un "sí" dudoso no ejecuta acciones
        return "act"
    if confirmable and intent == "deny":
        return "cancel"
    if awaiting == "option" and intent == "select_option":
        return "select_option"
    if conf < 0.6 or intent == "unknown":
        return "respond"
    if intent == "out_of_scope":
        return "handoff"
    if intent == "block_card":
        return "find_card"
    if intent in ("dispute_charge", "confirm", "deny", "select_option"):
        return "find_transaction"  # confirm/deny/select_option fuera de contexto con confianza alta: flujo nuevo
    return None  # intención agregada después de este test: solo se exige la propiedad de seguridad (nunca `act`)


def test_understand_routes_to_act_only_on_fresh_confirmation(stub_agent):
    agent, router = stub_agent
    table = []
    for awaiting, intent, conf, pending in itertools.product(AWAITING, INTENTS, CONFIDENCES, PENDING):
        action = None if pending == "none" else {
            "type": "open_dispute", "transaction_id": "T-ANA-5", "block_card": None, "card_label": None,
            "asked_turn": TURN - 1 if pending == "fresh" else TURN - 3}
        router.u = Understanding(intent, conf, "es", Slots())
        state = {"user_text": "texto 4111111111111111", "turn": TURN, "awaiting": awaiting, "pending_action": action,
                 "token": "t"}
        calls: list = []
        out = agent.understand(state, calls)
        assert calls == [], "understand no llama herramientas"
        assert out["next"] in EDGES["understand"]
        exp = _expected(awaiting, intent, conf, pending)
        if exp is None:
            assert out["next"] != "act", (awaiting, intent, conf, pending)
        else:
            assert out["next"] == exp, (awaiting, intent, conf, pending, out["next"])
        if awaiting == "confirmation" and out["next"] not in ("act", "cancel"):
            # una confirmación que no se usó en su turno se descarta: no puede reusarse más adelante. Única excepción
            # (#38): una respuesta ambigua a una pregunta FRESCA se re-pregunta en este turno, y esa nueva pregunta
            # vale solo para el turno siguiente (asked_turn = TURN).
            reasked = out.get("reply_prefix") and (out.get("pending_action") or {}).get("asked_turn") == TURN
            assert (out.get("awaiting") is None and out.get("pending_action") is None) or \
                (pending == "fresh" and reasked), (awaiting, intent, conf, pending)
        if awaiting == "confirmation" and pending != "fresh":
            assert router.seen[-1][1] is None, "a una confirmación vieja el router no la ve como pendiente"
        table.append((awaiting, intent, conf, pending, out["next"]))
    acts = [r for r in table if r[-1] == "act"]
    assert acts and all(r[0] == "confirmation" and r[1] == "confirm" and r[3] == "fresh" and r[2] >= 0.6
                        for r in acts)
    assert len(table) == len(AWAITING) * len(INTENTS) * len(CONFIDENCES) * len(PENDING)
    # el router recibe el texto ya enmascarado
    assert all("4111111111111111" not in t for t, _ in router.seen)


def test_regression_low_confidence_confirm_does_not_act(stub_agent):
    """Hallazgo de la tabla exhaustiva: antes, un "confirm" con confianza 0.0 (p. ej. de un router LLM dudoso)
    ejecutaba la acción; `min_confidence` solo se aplicaba a los pedidos nuevos."""
    agent, router = stub_agent
    router.u = Understanding("confirm", 0.1, "es", Slots())
    state = {"user_text": "mmm", "turn": 3, "awaiting": "confirmation", "token": "t",
             "pending_action": {"type": "block_card", "block_card": "PRD-ANA-CC", "card_label": "****1111",
                                "asked_turn": 2}}
    out = agent.understand(state, [])
    # #38: no actúa; re-pregunta explícitamente y esa pregunta nueva vale solo para el turno siguiente
    assert out["next"] == "respond" and out["reply_prefix"] == "reask_consent"
    assert out["pending_action"]["asked_turn"] == 3
