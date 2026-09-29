"""Guard de entrada: corre ANTES de cualquier modelo. Determinista y auditable.

- Detecta intentos de inyección / exfiltración (primera línea; no es la única defensa: aunque pasara,
  las herramientas solo devuelven datos del dueño de la sesión). `InjectionDetector` es la interfaz:
  `RegexDetector` (patrones, LÍNEA BASE y default) y `ClassifierDetector` (modelo preentrenado ONNX,
  opt-in con BANKAGENT_INJECTION_DETECTOR). Decisión y métricas: docs/adr/0005-deteccion-inyeccion.md.
- Enmascara PII (números de tarjeta/documento, emails, teléfonos) antes de que el texto llegue a un
  proveedor externo (LLM / Jev) o a los logs.
"""
from __future__ import annotations

import logging
import math
import os
import re
import unicodedata
from dataclasses import dataclass
from typing import Protocol

log = logging.getLogger(__name__)

INJECTION_PATTERNS = [
    r"ignor\w* (\w+ ){0,3}(instruc|regla|reglas|instruc\w*|prompt)",
    r"ignore (all |the )?(previous|prior|above) (instructions|rules)",
    r"(olvida|esquec\w*|forget|desconsidera\w*) (\w+ ){0,3}(instruc\w*|regla\w*|regra\w*|rules|prompt)",
    r"(system|sistema) ?prompt",
    r"modo (desarrollador|developer|dios)|developer mode|jailbreak",
    r"(ahora )?(eres|es|agora voce e|you are now) (un|uma|um|a)? ?(admin|administrador|root|otro asistente)",
    # Datos de OTRO cliente/usuario (explícito). Ya no se marca "la cuenta de María López, mi esposa" ni "los
    # movimientos de mi hermano": son reclamos legítimos y frecuentes; además, las herramientas solo ven la sesión.
    r"(cuenta|conta|datos|dados|saldo|transacc\w*|transac\w*|movimient\w*|tarjeta|cartao) (de|do|da) "
    r"(otro|otra|outro|outra) (cliente|usuario|usuaria|titular|persona|pessoa)",
    r"(muestra\w*|mostra\w*|mostre|dame|dime|pasame|ver|consulta\w*|revisa\w*|quiero ver|quero ver)\b.{0,40}\b"
    r"(de|do|da) (otro|otra|outro|outra) (cliente|usuario|usuaria|titular)",
    r"ignor\w* (\w+ ){0,3}(anterior\w*|previ\w*|antes|above|acima|todo lo que)",
    r"(olvida\w*|esquec\w*|forget) (todo|tudo|everything)",
    r"(finja|finge|fingi\w*|pretend\w*|haz de cuenta|hace de cuenta|faz de conta|actua como|atue como|act as|simul\w*)"
    r"\b.{0,40}\b(admin\w*|root|sistema|system|desarrollador|developer|superusuario|gerente|dios|sin restric\w*|"
    r"sem restric\w*)",
    r"</?\s*(user|system|assistant|usuario|sistema)\s*>",  # etiquetas de rol inyectadas
    r"^\s*(system|assistant)\s*:|\b(system|assistant)\s*:\s*(approve|ignore|you|reveal)",
    r"approve\w* (the |a )?refund",
    r"\bCLI-[A-Z0-9]{6,}\b",  # pedir un cliente por su ID interno
    r"(aprueba|aprova|autoriza|reembolsa|reembolsar|transfiere|transfira)\b.*\b(sin|sem) (validar|verificar|confirmar)",
]

PII_PATTERNS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[TARJETA]"),
    # (?<!...) en vez de \b: el match solo puede empezar al inicio de una racha; con \b, "a.a.a.…" sin @ se
    # re-escaneaba desde cada posición (cuadrático: 40k caracteres = 6,6 s, red team #33)
    (re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\+?\d{2,3}[ -]?\d{2,3}[ -]?\d{3,4}[ -]?\d{3,4}\b"), "[TELEFONO]"),
    (re.compile(r"\b[A-Z]{4}\d{6}[A-Z0-9]{8}\b"), "[CURP]"),
]


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c))


# ---------------------------------------------------------------- texto no confiable: normalización (#33)
# Red team #33: un "no" con un carácter de cero ancho ("n​o bloquees") o con una "о" cirílica se VE igual para
# el cliente pero el lector de consentimiento no lo reconocía, y se bloqueaba la tarjeta que el cliente había
# rechazado. Lo mismo con overrides bidireccionales (RLO) que llegaban al paquete del asesor. Raíz: cada componente
# leía el texto crudo. Ahora el texto del cliente se normaliza UNA vez, en la frontera (guard), y todo lo de abajo
# (detector, router, conversación, handoff) ve lo mismo que ve una persona.
_INVISIBLE_CATS = {"Cc", "Cf", "Cs", "Co", "Cn"}  # control, formato (cero ancho, bidi), surrogates, privados, sin asignar
# Letras cirílicas y griegas que se ven idénticas a letras latinas (subconjunto de Unicode confusables, UTS #39).
_CONFUSABLES = str.maketrans({
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d",
    "һ": "h", "ӏ": "l", "ԛ": "q", "ԝ": "w", "ɑ": "a", "ο": "o", "α": "a", "ε": "e", "ν": "v", "ρ": "p", "τ": "t",
    "ι": "i", "κ": "k", "υ": "u", "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P",
    "С": "C", "Т": "T", "Х": "X", "І": "I", "Ј": "J", "Ѕ": "S", "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H",
    "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X"})
_WORD = re.compile(r"\w+")
_LATIN = re.compile(r"[A-Za-zÀ-ɏ]")


def strip_invisible(text: str) -> str:
    """Quita caracteres que no se ven (cero ancho, marcas/overrides bidi, BOM, surrogates sueltos) y cambia los
    controles por espacio. Conserva \\n y \\t. Se usa para el texto del cliente y para datos que se muestran."""
    out = []
    for ch in text:
        cat = unicodedata.category(ch)
        if ch in "\n\t" or cat not in _INVISIBLE_CATS:
            out.append(ch)
        elif cat == "Cc":
            out.append(" ")
    return "".join(out)


def _unconfuse(m: re.Match) -> str:
    w = m.group(0)
    return w.translate(_CONFUSABLES) if _LATIN.search(w) else w  # solo palabras con escritura mezclada


def normalize_input(text: str) -> str:
    """Forma canónica del texto del cliente: NFKC (ancho completo -> ASCII), sin invisibles y sin homoglifos
    cirílicos/griegos dentro de palabras latinas. Lo que el agente lee es lo que el cliente ve."""
    t = strip_invisible(unicodedata.normalize("NFKC", text))
    return _WORD.sub(_unconfuse, t)


# Celdas que una hoja de cálculo interpreta como fórmula (OWASP "CSV Injection").
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")


def safe_display(value):
    """Para lo que se muestra o exporta a una persona (paquete de handoff, consola del asesor, CSV): sin
    invisibles y sin celdas-fórmula (se antepone un apóstrofo, como recomienda OWASP). Recorre dict/list."""
    if isinstance(value, dict):
        return {k: safe_display(v) for k, v in value.items()}
    if isinstance(value, list):
        return [safe_display(v) for v in value]
    if isinstance(value, str):
        v = strip_invisible(value)
        return "'" + v if v.startswith(FORMULA_START) else v
    return value


# Letras sueltas separadas por espacios ("I g n o r a   t u s ..."): se juntan y se buscan estas raíces.
SPACED_OUT = re.compile(r"(?:\b\w\b\s+){5,}\b\w\b")
SPACED_ROOTS = ("ignor", "instruc", "system", "prompt", "admin", "olvida", "regla", "jailbreak", "esquec")


def detect_injection(text: str) -> str | None:
    """Devuelve el patrón que coincidió (para el registro) o None."""
    folded = _fold(normalize_input(text))
    for p in INJECTION_PATTERNS:
        flags = 0 if p.startswith(r"\bCLI") or "[A-Z]" in p else re.IGNORECASE
        if re.search(p, folded, flags):
            return p
    spaced = "".join(SPACED_OUT.findall(folded)).lower()
    if spaced and sum(r in re.sub(r"\s+", "", spaced) for r in SPACED_ROOTS) >= 1:
        return "spaced_out_letters"
    return None


class InjectionDetector(Protocol):
    """score() en [0, 1]: más alto = más probable que sea inyección. Se bloquea si score >= threshold."""

    name: str
    threshold: float

    def score(self, text: str) -> float: ...

    def detect(self, text: str) -> str | None:
        """Motivo legible para la traza (patrón o score) o None si no bloquea."""
        ...


class RegexDetector:
    """Línea base: patrones es/pt/en. Determinista, sin dependencias, < 1 ms."""

    name = "regex"
    threshold = 0.5

    def score(self, text: str) -> float:
        return 1.0 if detect_injection(text) else 0.0

    def detect(self, text: str) -> str | None:
        p = detect_injection(text)
        return f"pattern={p}" if p else None


@dataclass(frozen=True)
class ModelSpec:
    repo: str
    revision: str   # commit fijo: el modelo que corre es exactamente el evaluado
    onnx: str
    tokenizer: str
    output: str     # "logits" (2 clases) | "margin" (logit inyección - logit benigno)
    license: str
    threshold: float  # elegido en el split de desarrollo, nunca en test (ver ADR 0005)
    max_len: int = 512


MODELS: dict[str, ModelSpec] = {
    "mdeberta-en-es": ModelSpec("edithngalame/mdeberta-v3-prompt-injection-en-es", "74be2ffb282be41d57942b40eee54da4cdb6bd7c",
                                "onnx/model.onnx", "onnx/tokenizer.json", "margin", "MIT", threshold=0.01336),
    "protectai-v2": ModelSpec("protectai/deberta-v3-base-prompt-injection-v2", "90c9989b1a342275dd0d1a95aad283c04e075671",
                              "onnx/model.onnx", "onnx/tokenizer.json", "logits", "Apache-2.0", threshold=0.999988),
}


def margin_to_prob(margin: float) -> float:
    """Softmax de 2 clases == sigmoide del margen (logit inyección - logit benigno)."""
    return 1.0 / (1.0 + math.exp(-max(-60.0, min(60.0, margin))))


class ClassifierDetector:
    """Clasificador preentrenado (ONNX Runtime, CPU). Carga perezosa: el modelo se abre en el primer
    score(). Si faltan dependencias o el modelo no está disponible, cae a `fallback` (regex) y lo deja
    en el log: el agente nunca se queda sin guard."""

    def __init__(self, model: str = "mdeberta-en-es", threshold: float | None = None,
                 fallback: InjectionDetector | None = None, local_only: bool = False):
        self.spec = MODELS[model]
        self.model = model
        self.threshold = self.spec.threshold if threshold is None else threshold
        self.fallback = fallback or RegexDetector()
        self.local_only = local_only
        self._session = self._tok = None
        self._inputs: set[str] = set()
        self._failed: str | None = None

    @property
    def name(self) -> str:
        return f"classifier:{self.model}" if self._failed is None else f"{self.fallback.name}(fallback)"

    def _load(self) -> bool:
        if self._session is not None or self._failed is not None:
            return self._failed is None
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from tokenizers import Tokenizer

            def get(f):
                return hf_hub_download(self.spec.repo, f, revision=self.spec.revision, local_files_only=self.local_only)

            tok = Tokenizer.from_file(get(self.spec.tokenizer))
            tok.enable_truncation(self.spec.max_len)
            tok.enable_padding(pad_id=tok.token_to_id("[PAD]") or 0)
            opts = ort.SessionOptions()
            opts.intra_op_num_threads = int(os.environ.get("BANKAGENT_ORT_THREADS", "0"))
            self._session = ort.InferenceSession(get(self.spec.onnx), opts, providers=["CPUExecutionProvider"])
            self._inputs = {i.name for i in self._session.get_inputs()}
            self._tok = tok
        except Exception as e:  # sin red, sin extras instalados, archivo corrupto...
            self._session = None
            self._failed = f"{type(e).__name__}: {e}"[:200]
            log.warning("ClassifierDetector(%s) no disponible, se usa %s: %s", self.model, self.fallback.name, self._failed)
        return self._failed is None

    @property
    def available(self) -> bool:
        return self._load()

    def score_batch(self, texts: list[str]) -> list[float]:
        if not self._load():
            return [self.fallback.score(t) for t in texts]
        import numpy as np

        enc = self._tok.encode_batch(list(texts))
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in self._inputs:
            feed["token_type_ids"] = np.zeros_like(feed["input_ids"])
        out = self._session.run(None, {k: v for k, v in feed.items() if k in self._inputs})[0]
        margins = out.reshape(-1) if self.spec.output == "margin" else out[:, 1] - out[:, 0]
        return [margin_to_prob(float(m)) for m in margins]

    def score(self, text: str) -> float:
        return self.score_batch([text])[0]

    def detect(self, text: str) -> str | None:
        if not self._load():
            return self.fallback.detect(text)
        s = self.score(text)
        return f"{self.name}={s:.3f}" if s >= self.threshold else None


class AnyDetector:
    """Bloquea si CUALQUIERA de los detectores bloquea (p. ej. regex OR clasificador)."""

    threshold = 0.5

    def __init__(self, *detectors: InjectionDetector):
        self.detectors = detectors

    @property
    def name(self) -> str:
        return "any(" + ",".join(d.name for d in self.detectors) + ")"

    def score(self, text: str) -> float:
        return 1.0 if self.detect(text) else 0.0

    def detect(self, text: str) -> str | None:
        return next((r for d in self.detectors if (r := d.detect(text))), None)


def detector_from_env(env: dict | None = None) -> InjectionDetector:
    """BANKAGENT_INJECTION_DETECTOR = regex (default) | classifier | combined.
    BANKAGENT_INJECTION_MODEL = clave de MODELS · BANKAGENT_INJECTION_THRESHOLD = umbral (float)."""
    env = os.environ if env is None else env
    kind = env.get("BANKAGENT_INJECTION_DETECTOR", "regex").strip().lower()
    if kind == "regex":
        return RegexDetector()
    thr = env.get("BANKAGENT_INJECTION_THRESHOLD")
    clf = ClassifierDetector(env.get("BANKAGENT_INJECTION_MODEL", "mdeberta-en-es"),
                             threshold=float(thr) if thr else None)
    if kind == "classifier":
        return clf
    if kind == "combined":
        return AnyDetector(RegexDetector(), clf)
    raise ValueError(f"BANKAGENT_INJECTION_DETECTOR desconocido: {kind!r}")


def redact(text: str) -> str:
    for rx, repl in PII_PATTERNS:
        text = rx.sub(repl, text)
    return text
