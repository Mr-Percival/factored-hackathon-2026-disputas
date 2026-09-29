"""Cadena de suministro (#17, LLM03): locks con hash al día con pyproject.toml y acciones de CI fijadas por SHA."""
import glob
import os
import re
import tomllib

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def _declared(extras: tuple[str, ...]) -> set[str]:
    with open(os.path.join(ROOT, "pyproject.toml"), "rb") as f:
        proj = tomllib.load(f)["project"]
    reqs = list(proj["dependencies"]) + [r for e in extras for r in proj["optional-dependencies"][e]]
    return {_norm(re.match(r"[A-Za-z0-9_.-]+", r).group(0)) for r in reqs}


def _locked(path: str) -> tuple[set[str], list[str]]:
    with open(os.path.join(ROOT, path), encoding="utf-8") as f:
        text = f.read()
    pins = re.findall(r"^([A-Za-z0-9_.-]+)(?:\[[^\]]*\])?==\S+ \\\n((?:\s+--hash=sha256:[0-9a-f]{64}(?: \\)?\n)+)",
                      text, re.M)
    lines = [ln for ln in text.splitlines() if re.match(r"^[A-Za-z0-9]", ln)]
    unhashed = [ln for ln in lines if ln.split("==")[0] not in {p for p, _ in pins}]
    return {_norm(p) for p, _ in pins}, unhashed


def test_locks_cover_declared_dependencies_with_hashes():
    for path, extras in (("requirements/api.lock", ("api", "ml")), ("requirements/ci.lock", ("dev", "api", "ml"))):
        locked, unhashed = _locked(path)
        assert not unhashed, f"{path}: sin hash o sin versión exacta: {unhashed}"
        missing = _declared(extras) - locked
        assert not missing, f"{path} no cubre {sorted(missing)}: correr `bash scripts/lock.sh`"


def test_workflow_actions_are_pinned_by_sha():
    bad = []
    for wf in glob.glob(os.path.join(ROOT, ".github", "workflows", "*.yml")):
        with open(wf, encoding="utf-8") as f:
            for n, ln in enumerate(f, 1):
                m = re.search(r"uses:\s*(\S+)", ln)
                if m and not re.fullmatch(r"[\w.-]+/[\w./-]+@[0-9a-f]{40}", m.group(1)) and not m.group(1).startswith("./"):
                    bad.append(f"{os.path.basename(wf)}:{n} {m.group(1)}")
                elif m and "#" not in ln:
                    bad.append(f"{os.path.basename(wf)}:{n} sin comentario con el tag")
    assert not bad, bad
