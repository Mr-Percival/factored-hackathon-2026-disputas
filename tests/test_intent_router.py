"""Router de intención aprendido (#42, ADR 0009): lógica del HybridRouter con un encoder de juguete (sin red ni
modelos), persistencia de artefactos, el artefacto lite versionado y el agente completo con router="embeddings".
El modelo full (MiniLM ONNX) solo se prueba si ya está en la caché local."""
import datetime as dt
import json

import pytest

np = pytest.importorskip("numpy")

from bankagent.embedding_router import HybridRouter  # noqa: E402
from bankagent.factory import build_agent  # noqa: E402
from bankagent.intent_model import (DEFAULT_DIR, FULL_DIR, LABELS, ROUTE, CharNgramEncoder, IntentModel,  # noqa: E402
                                    char_ngrams, error_cost, load_intent_model)
from bankagent.observability import LLM_FIELDS  # noqa: E402

TODAY = dt.date(2026, 6, 17)


class StubEncoder:
    """Una dimensión por intención, activada por una palabra clave: el test controla exactamente la salida."""

    name = "stub"
    KEYS = {"reconozco": "dispute_charge", "perdi": "block_card", "hackearon": "account_takeover",
            "asesor": "human_request", "reclamo": "dispute_status", "retiren": "cancel_dispute",
            "saldo": "out_of_scope", "gracias": "closing"}

    def encode(self, texts):
        x = np.zeros((len(texts), len(LABELS)), dtype=np.float32)
        for i, t in enumerate(texts):
            hit = [LABELS.index(v) for k, v in self.KEYS.items() if k in t.lower()]
            for j in hit:
                x[i, j] = 1.0
            if not hit:
                x[i, LABELS.index("unknown")] = 0.3  # débil: debe abstenerse
        return x

    def spec(self):
        return {"type": "stub"}


def stub_model(threshold=0.5) -> IntentModel:
    return IntentModel(StubEncoder(), np.eye(len(LABELS)) * 6, np.zeros(len(LABELS)), LABELS, 1.0, threshold,
                       {"model_id": "stub", "version": "test", "candidate": "stub"})


@pytest.fixture
def router():
    return HybridRouter(intent_model=stub_model())


def test_model_picks_intent_and_rules_fill_slots(router):
    u = router.understand("no reconozco un cargo de 350 del 10/06/2026", TODAY, None)
    assert u.intent == "dispute_charge" and u.confidence > 0.9
    assert u.slots.amount == 350 and u.slots.date_from == dt.date(2026, 6, 10)  # slots de RuleRouter
    assert u.router == "embed:stub" and u.llm["label"] == "dispute_charge" and not u.llm["abstained"]


def test_every_user_intent_reaches_the_graph_contract(router):
    from bankagent.understanding import INTENTS
    for key, label in StubEncoder.KEYS.items():
        u = router.understand(f"hola {key}", TODAY, None)
        assert u.intent == label and u.intent in INTENTS


def test_low_confidence_abstains_to_unknown(router):
    u = router.understand("mmm", TODAY, None)
    assert u.intent == "unknown" and u.llm["abstained"] and u.confidence < 0.5


def test_context_replies_are_delegated_to_rules(router):
    """Consentimiento y elección de opción dependen de la pregunta pendiente: los decide RuleRouter."""
    assert router.understand("sí, dale", TODAY, "confirmation").intent == "confirm"
    assert router.understand("no, mejor no", TODAY, "confirmation").intent == "deny"
    u = router.understand("la 2", TODAY, "option")
    assert u.intent == "select_option" and u.slots.option == 2 and "rules:context" in u.router
    assert router.understand("ninguna de esas", TODAY, "option").intent == "none_of_these"


def test_details_reply_keeps_rules(router):
    u = router.understand("de 151 dólares", TODAY, "details")
    assert u.intent == "unknown" and u.slots.amount == 151 and "rules:details" in u.router


def test_missing_model_falls_back_to_rules_and_says_so(tmp_path):
    r = HybridRouter(model_dir=tmp_path / "no-existe")
    u = r.understand("no reconozco un cargo de 77", TODAY, None)
    assert u.intent == "dispute_charge"  # respuesta de RuleRouter
    assert u.router == "rules(fallback:model_unavailable)"
    assert u.llm["fallback"] == "model_unavailable" and u.llm["errors"]


def test_telemetry_fits_the_trace_contract(router):
    llm = router.understand("no reconozco un cargo", TODAY, None).llm
    assert set(LLM_FIELDS) <= set(llm) and llm["cost_usd"] == 0 and llm["provider"] == "local"


def test_char_model_roundtrip(tmp_path):
    texts = ["no reconozco este cargo", "perdí la tarjeta", "hola", "quiero un asesor"] * 3
    vocab = sorted({g for t in texts for g in char_ngrams(t)})
    enc = CharNgramEncoder({g: i for i, g in enumerate(vocab)}, np.ones(len(vocab)))
    rng = np.random.default_rng(0)
    m = IntentModel(enc, rng.normal(size=(len(vocab), len(LABELS))), rng.normal(size=len(LABELS)), LABELS, 0.7, 0.4,
                    {"model_id": "char-test"})
    m.save(tmp_path)
    back = load_intent_model(tmp_path)
    assert back.threshold == 0.4 and back.labels == LABELS
    assert np.allclose(back.predict_proba(texts), m.predict_proba(texts), atol=2e-3)  # pesos en float16


def test_char_ngrams_normalize_accents_digits_and_repeats():
    assert char_ngrams("Perdí", 2, 2) == char_ngrams("perdi", 2, 2)
    assert char_ngrams("cargo 350", 3, 3) == char_ngrams("cargo 999", 3, 3)
    assert char_ngrams("nooooo", 2, 5) == char_ngrams("noo", 2, 5)


def test_error_cost_orders_the_mistakes_that_matter():
    assert error_cost("dispute_charge", "dispute_charge") == 0
    assert error_cost("human_request", "dispute_charge") == 3 > error_cost("unknown", "dispute_charge") == 2
    assert error_cost("dispute_charge", "unknown") == 0.5  # aclarar es barato
    assert error_cost("account_takeover", "out_of_scope") == 1 > error_cost("human_request", "out_of_scope")
    assert set(ROUTE) == set(LABELS)


# ------------------------------------------------------------------ artefacto versionado (lite)
lite_present = pytest.mark.skipif(not (DEFAULT_DIR / "meta.json").exists(), reason="sin artefacto lite")


@lite_present
def test_versioned_lite_artifact_is_traceable_and_small():
    meta = json.loads((DEFAULT_DIR / "meta.json").read_text(encoding="utf-8"))
    assert meta["labels"] == list(LABELS) and meta["encoder"]["type"] == "char"
    assert len(meta["corpus_sha256"]) == 64 and 0 < meta["threshold"] < 1 and meta["temperature"] > 0
    assert sum(p.stat().st_size for p in DEFAULT_DIR.iterdir()) < 5_000_000


@lite_present
def test_lite_model_on_clear_messages():
    m = load_intent_model(DEFAULT_DIR)
    for text, label in [("no reconozco un cargo de 350 en mi tarjeta", "dispute_charge"),
                        ("perdí mi tarjeta, bloquéenla por favor", "block_card"),
                        ("quero falar com um atendente humano", "human_request")]:
        assert m.predict(text).label == label


@lite_present
def test_agent_with_learned_router_disputes_with_confirmation(env):
    agent = build_agent(env.tools, router="embeddings")
    tok, th = env.login("CLI-ANA"), env.thread()
    r = agent.chat(th, tok, "No reconozco un cargo de 77 dólares")
    und = next(e for e in r["trace"] if e["node"] == "understand")
    assert und["llm"]["provider"] == "local" and "embed:" in und["detail"]
    assert r["outcome"] == "clarify" and "Confirmas" in r["reply"]
    r = agent.chat(th, tok, "sí")
    assert r["outcome"] == "resolved" and r["action_result"]["dispute"]["verified"]


@pytest.mark.skipif(not (FULL_DIR / "meta.json").exists(), reason="sin artefacto full")
def test_full_model_if_cached():
    pytest.importorskip("onnxruntime")
    pytest.importorskip("tokenizers")
    hub = pytest.importorskip("huggingface_hub")
    meta = json.loads((FULL_DIR / "meta.json").read_text(encoding="utf-8"))
    onnx = next(p for p in meta["encoder"]["parts"] if p["type"] == "onnx")
    cached = hub.try_to_load_from_cache(onnx["model_id"], onnx["model_file"], revision=onnx["revision"])
    if not isinstance(cached, str):  # nunca descargar 250 MB en CI
        pytest.skip("modelo preentrenado fuera de la caché local")
    try:
        m = load_intent_model(FULL_DIR)
        m.warmup()
    except Exception as e:  # noqa: BLE001 - sin caché del modelo preentrenado (CI sin red): se omite
        pytest.skip(f"modelo preentrenado no disponible: {e}")
    assert m.predict("no reconozco un cargo de 350").label == "dispute_charge"
