"""Guard de entrada: corre ANTES de cualquier modelo. Determinista y auditable.

- Detecta intentos de inyección / exfiltración por patrones (primera línea; no es la única defensa:
  aunque pasara, las herramientas solo devuelven datos del dueño de la sesión).
- Enmascara PII (números de tarjeta/documento, emails, teléfonos) antes de que el texto llegue a un
  proveedor externo (LLM / Jev) o a los logs.
"""
from __future__ import annotations

import re
import unicodedata

INJECTION_PATTERNS = [
    r"ignor\w* (\w+ ){0,3}(instruc|regla|reglas|instruc\w*|prompt)",
    r"ignore (all |the )?(previous|prior|above) (instructions|rules)",
    r"(olvida|esquec\w*|forget|desconsidera\w*) (\w+ ){0,3}(instruc\w*|regla\w*|regra\w*|rules|prompt)",
    r"(system|sistema) ?prompt",
    r"modo (desarrollador|developer|dios)|developer mode|jailbreak",
    r"(ahora )?(eres|es|agora voce e|you are now) (un|uma|um|a)? ?(admin|administrador|root|otro asistente)",
    r"(cuenta|conta|datos|dados|saldo|transacc\w*|movimient\w*) de (otro|otra|outro|outra|mi (vecino|jefe|hermano)|[A-Z][a-z]+ [A-Z])",
    r"\bCLI-[A-Z0-9]{6,}\b",  # pedir un cliente por su ID interno
    r"(aprueba|aprova|autoriza|reembolsa|reembolsar|transfiere|transfira)\b.*\b(sin|sem) (validar|verificar|confirmar)",
]

PII_PATTERNS = [
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[TARJETA]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.]+\b"), "[EMAIL]"),
    (re.compile(r"\+?\d{2,3}[ -]?\d{2,3}[ -]?\d{3,4}[ -]?\d{3,4}\b"), "[TELEFONO]"),
    (re.compile(r"\b[A-Z]{4}\d{6}[A-Z0-9]{8}\b"), "[CURP]"),
]


def _fold(text: str) -> str:
    t = unicodedata.normalize("NFKD", text)
    return "".join(c for c in t if not unicodedata.combining(c))


def detect_injection(text: str) -> str | None:
    """Devuelve el patrón que coincidió (para el registro) o None."""
    folded = _fold(text)
    for p in INJECTION_PATTERNS:
        flags = 0 if p.startswith(r"\bCLI") or "[A-Z]" in p else re.IGNORECASE
        if re.search(p, folded, flags):
            return p
    return None


def redact(text: str) -> str:
    for rx, repl in PII_PATTERNS:
        text = rx.sub(repl, text)
    return text
