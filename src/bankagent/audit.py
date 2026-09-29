"""Log de auditoría append-only con cadena de hashes (JSONL).

Cada línea es un registro de la traza del grafo (un nodo ejecutado):

    {seq, ts, thread, turn, node, next, tools, detail, outcome, prev_hash, hash}

    hash = sha256(prev_hash + json_canonico(registro_sin_hash))

El primer registro encadena contra `GENESIS_HASH` (64 ceros). Modificar un campo, borrar una línea
intermedia o reordenar líneas rompe la cadena y `verify` devuelve el primer `seq` inválido.

Qué NO guarda (minimización de PII): el texto del cliente, ni siquiera enmascarado. `thread` es un
seudónimo (HMAC-SHA256 del id de conversación con una clave del entorno). `detail` pasa por
`guard.redact` por si un nodo futuro incluyera texto libre.

Límites conocidos (ver docs/threat-model.md): la cadena detecta ediciones, pero no el truncado del final
del archivo ni que alguien reescriba TODA la cadena. Para eso hay que anclar el último hash fuera del
sistema (`verify(..., expected_head=...)`) y, en producción, usar almacenamiento WORM.

CLI:  python -m bankagent.audit verify <ruta> [--head <hash esperado>]
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import os
import sys
import threading

from .guard import redact

GENESIS_HASH = "0" * 64
KEY_ENV = "BANKAGENT_AUDIT_KEY"  # clave para seudonimizar el id de conversación (en producción: KMS)


def canonical_json(obj: dict) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def chain_hash(prev_hash: str, record_without_hash: dict) -> str:
    return hashlib.sha256((prev_hash + canonical_json(record_without_hash)).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: str, key: str | None = None):
        self.path = path
        self._key = (key if key is not None else os.environ.get(KEY_ENV, "")).encode("utf-8")
        self._lock = threading.Lock()
        self.seq, self.head = 0, GENESIS_HASH
        # Continuidad tras reinicios: se retoma desde el último registro del archivo existente.
        if os.path.exists(path):
            last = None
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if line.strip():
                        last = line
            if last:
                rec = json.loads(last)
                self.seq, self.head = rec["seq"], rec["hash"]

    def pseudonym(self, thread_id: str) -> str:
        return hmac.new(self._key, thread_id.encode("utf-8"), hashlib.sha256).hexdigest()[:16]

    def append(self, thread_id: str, entry: dict, outcome: str | None = None) -> dict:
        """Persiste un registro de la traza (`entry` como lo arma `Agent._traced`)."""
        with self._lock:
            rec = {
                "seq": self.seq + 1,
                "ts": dt.datetime.now(dt.timezone.utc).isoformat(timespec="milliseconds"),
                "thread": self.pseudonym(thread_id),
                "turn": entry.get("turn"),
                "node": entry.get("node"),
                "next": entry.get("next"),
                "tools": entry.get("tools") or [],
                "detail": redact(str(entry["detail"])) if entry.get("detail") is not None else None,
                "outcome": outcome,
                "prev_hash": self.head,
            }
            rec["hash"] = chain_hash(self.head, rec)
            with open(self.path, "a", encoding="utf-8", newline="\n") as f:
                f.write(canonical_json(rec) + "\n")
                f.flush()
                os.fsync(f.fileno())
            self.seq, self.head = rec["seq"], rec["hash"]
            return rec


def verify(path: str, expected_head: str | None = None) -> tuple[bool, int | None]:
    """Recorre la cadena. Devuelve (True, None) o (False, primer seq inválido).

    Con `expected_head` (último hash anclado fuera del sistema) también detecta el truncado del final.
    """
    prev, expected_seq = GENESIS_HASH, 1
    with open(path, encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            try:
                rec = json.loads(line)
                body = {k: v for k, v in rec.items() if k != "hash"}
                ok = (rec["seq"] == expected_seq and rec["prev_hash"] == prev
                      and chain_hash(prev, body) == rec["hash"])
            except (ValueError, KeyError, TypeError):
                ok = False
            if not ok:
                return False, expected_seq
            prev, expected_seq = rec["hash"], expected_seq + 1
    if expected_head is not None and prev != expected_head:
        return False, expected_seq
    return True, None


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="python -m bankagent.audit")
    sub = ap.add_subparsers(dest="cmd", required=True)
    v = sub.add_parser("verify", help="verifica la cadena de hashes de un log de auditoría")
    v.add_argument("path")
    v.add_argument("--head", default=None, help="último hash anclado externamente (detecta truncado)")
    a = ap.parse_args(argv)
    ok, bad = verify(a.path, a.head)
    if ok:
        print(f"OK: cadena íntegra ({a.path}), último hash={AuditLog(a.path).head}")
        return 0
    print(f"FALLA: la cadena se rompe en seq={bad} ({a.path})")
    return 1


if __name__ == "__main__":
    sys.exit(main())
