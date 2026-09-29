"""Verifica que la documentación pública no apunte a cosas que no existen (#45).

    python scripts/check_docs.py            # código 1 si hay referencias rotas

Revisa README.md, CONTRIBUTING.md, docs/**/*.md, evals/**/*.md, web/README.md y reports/*.md:
- enlaces Markdown relativos `[texto](ruta#ancla)`: el archivo existe y, si apunta a un `.md` con ancla, el
  encabezado existe (slug al estilo GitHub);
- rutas del repo entre backticks (`tests/…`, `src/…`, `scripts/…`, `reports/…`, `docs/…`, `config/…`, `evals/…`,
  `web/…`, `models/…`, `corpus/…`, `.github/…`): el archivo o directorio existe (se ignoran comodines y plantillas);
- referencias `archivo.py::nombre` y las continuaciones `::nombre` (mismo archivo que la anterior en la línea o
  la celda): la función o clase existe en ese archivo.
No toca la red: los enlaces http(s) no se revisan. `data/` no está versionado y se ignora.
"""
from __future__ import annotations

import glob
import os
import re
import sys
import unicodedata

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATTERNS = ["README.md", "CONTRIBUTING.md", "docs/**/*.md", "evals/**/*.md", "web/README.md", "reports/*.md"]
TOP = ("tests/", "src/", "scripts/", "reports/", "docs/", "config/", "evals/", "web/", "models/", "corpus/",
       ".github/")
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)\)|!\[[^\]]*\]\(([^)\s]+)\)")
CODE = re.compile(r"`([^`\n]+)`")
FENCE = re.compile(r"^\s*(```|~~~)")


def slug(heading: str) -> str:
    """Ancla al estilo GitHub: minúsculas, sin puntuación salvo guiones y guiones bajos, espacios → '-'."""
    h = re.sub(r"<[^>]+>", "", heading).strip().lower()
    h = h.replace("`", "")
    out = []
    for ch in h:
        if ch in (" ",):
            out.append("-")
        elif ch in "-_" or ch.isalnum() or unicodedata.category(ch).startswith("M"):
            out.append(ch)
    return "".join(out)


def anchors(path: str) -> set[str]:
    seen: dict[str, int] = {}
    out = set()
    in_fence = False
    for line in open(path, encoding="utf-8"):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if m and not in_fence:
            s = slug(m.group(1))
            n = seen.get(s, 0)
            seen[s] = n + 1
            out.add(s if n == 0 else f"{s}-{n}")
    return out


def defined(path: str, name: str) -> bool:
    src = open(path, encoding="utf-8").read()
    return re.search(rf"^\s*(async\s+)?(def|class)\s+{re.escape(name)}\b", src, re.M) is not None


def repo_path(token: str) -> str | None:
    """Ruta del repo dentro de un fragmento de código, o None si no parece una."""
    t = token.strip().split()[0] if token.strip() else ""
    t = t.rstrip(".,;:)")
    if not t.startswith(TOP) or any(c in t for c in "*{}<>[]$|…") or "NNNN" in t:
        return None
    return t.split("#")[0]


def exists(path: str, md_dir: str) -> bool:
    """Existe desde la raíz o relativa al .md (web/README.md cita `src/api/…` de web/); sin extensión vale
    como prefijo de archivo (`evals/cases/test` = el split test)."""
    for base in (ROOT, md_dir):
        full = os.path.join(base, path)
        if os.path.exists(full) or glob.glob(full + ".*"):
            return True
    return False


def check_file(md: str, errors: list[str]) -> None:
    rel = os.path.relpath(md, ROOT).replace(os.sep, "/")
    base = os.path.dirname(md)
    in_fence = False
    for n, line in enumerate(open(md, encoding="utf-8"), 1):
        if FENCE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        for m in LINK.finditer(line):
            target = m.group(1) or m.group(2)
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I) or target.startswith("#") and not target[1:]:
                continue
            path, _, anchor = target.partition("#")
            full = os.path.normpath(os.path.join(base, path)) if path else md
            if not os.path.exists(full):
                errors.append(f"{rel}:{n}: enlace roto -> {target}")
            elif anchor and full.endswith(".md") and anchor.lower() not in anchors(full):
                errors.append(f"{rel}:{n}: ancla inexistente -> {target}")
        # Referencias en backticks; `::nombre` continúa el último archivo citado en la misma celda/línea.
        for cell in line.split("|"):
            last_py = None
            for m in CODE.finditer(cell):
                tok = m.group(1).strip()
                if tok.startswith("::") and last_py:
                    name = re.match(r"::([A-Za-z_]\w*)", tok)
                    if name and not defined(os.path.join(ROOT, last_py), name.group(1)):
                        errors.append(f"{rel}:{n}: {last_py}::{name.group(1)} no existe")
                    continue
                p = repo_path(tok)
                if not p:
                    continue
                path, _, name = p.partition("::")
                if not exists(path, base):
                    errors.append(f"{rel}:{n}: ruta inexistente -> {path}")
                    continue
                if path.endswith(".py") and os.path.exists(os.path.join(ROOT, path)):
                    last_py = path
                    if name and not defined(os.path.join(ROOT, path), re.match(r"\w+", name).group(0)):
                        errors.append(f"{rel}:{n}: {path}::{name} no existe")


def main() -> int:
    files = sorted({f for p in PATTERNS for f in glob.glob(os.path.join(ROOT, p), recursive=True)})
    errors: list[str] = []
    for f in files:
        if "node_modules" in f:
            continue
        check_file(f, errors)
    for e in errors:
        print(e)
    print(f"check_docs: {len(files)} archivos, {len(errors)} referencias rotas")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
