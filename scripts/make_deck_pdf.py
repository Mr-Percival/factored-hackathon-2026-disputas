"""Deck en HTML + PDF desde docs/pitch/deck.md (misma fuente que deck.pptx).

    PYTHONPATH=src python scripts/make_deck.py        # regenera deck.md / deck.pptx con metrics.yaml
    python scripts/make_deck_pdf.py [--shots]          # -> docs/pitch/deck.html, deck.pdf (+ capturas por slide)

Por qué existe: el PDF se ve igual en cualquier equipo (el pptx depende de fuentes y de la versión de
PowerPoint) y se puede revisar visualmente sin Office, con Chrome/Edge en modo headless.
Las notas del orador no van en las slides: van a un anexo al final del PDF.
"""
from __future__ import annotations

import argparse
import html
import os
import re
import shutil
import subprocess

import markdown

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PITCH = os.path.join(ROOT, "docs", "pitch")
BROWSERS = [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
            r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
            "google-chrome", "chromium", "chromium-browser", "msedge"]

CSS = """
@page { size: 1920px 1080px; margin: 0; }
:root { --ink:#0b0b0b; --ink2:#52514e; --ink3:#8a8984; --blue:#2a78d6; --orange:#eb6834;
        --pending:#b54a1a; --card:#f4f4f2; --tint:#eaf2fc; }
* { box-sizing: border-box; }
html, body { margin:0; background:#fff; color:var(--ink);
  font-family: "Segoe UI", system-ui, -apple-system, "Helvetica Neue", Arial, sans-serif; }
.slide { width:1920px; height:1080px; padding:88px 120px 72px; position:relative; overflow:hidden;
  page-break-after:always; display:flex; flex-direction:column; }
.slide::before { content:""; position:absolute; left:0; top:0; width:100%; height:10px; background:var(--blue); }
.slide h2 { font-size:64px; line-height:1.1; margin:0 0 8px; font-weight:700; letter-spacing:-0.5px; max-width:1600px; }
.slide h2 + p em { font-size:30px; color:var(--blue); font-style:normal; font-weight:600; }
.slide .body { display:flex; gap:64px; flex:1; min-height:0; margin-top:28px; align-items:flex-start; }
.slide .col { flex:1; min-width:0; }
.slide .body.stack { flex-direction:column; gap:32px; }
.slide .body.stack .col.wide img { width:100%; max-height:420px; }
.slide .body.stack ul { columns:2; column-gap:64px; font-size:28px; }
.slide img { max-width:100%; max-height:600px; object-fit:contain; border-radius:8px; }
.slide ul, .slide ol { font-size:32px; line-height:1.45; padding-left:1.1em; margin:0; }
.slide li { margin:0 0 18px; }
.slide li strong { color:var(--blue); }
.slide p { font-size:28px; line-height:1.45; color:var(--ink2); margin:0 0 16px; }
.slide table { border-collapse:collapse; font-size:24px; width:100%; }
.slide th { text-align:left; color:var(--ink3); font-weight:600; border-bottom:2px solid var(--ink);
  padding:12px 16px; font-size:20px; text-transform:uppercase; letter-spacing:0.5px; }
.slide td { padding:14px 16px; border-bottom:1px solid #e3e2de; vertical-align:top; }
.slide td strong { font-size:28px; }
.slide code { font-family:"Cascadia Code", Consolas, monospace; font-size:0.85em; background:var(--card);
  padding:2px 8px; border-radius:6px; }
.slide sub { position:absolute; left:120px; right:120px; bottom:36px; font-size:18px; color:var(--ink3); line-height:1.4; }
.pending { color:var(--pending); font-weight:700; background:#fff1ea; padding:0 6px; border-radius:4px; }
.num { position:absolute; right:120px; top:40px; font-size:20px; color:var(--ink3); }
.notes { width:1920px; min-height:1080px; padding:88px 120px; page-break-after:always; }
.notes h2 { font-size:44px; margin:0 0 32px; }
.notes h3 { font-size:28px; margin:36px 0 8px; color:var(--blue); }
.notes p { font-size:24px; line-height:1.5; color:var(--ink2); max-width:1600px; margin:0; }
body.single .slide, body.single .notes { display:none; }
body.single .slide.show { display:flex; }
"""

JS = """
const n = parseInt((location.hash || '').replace('#s', ''), 10);
if (n) { document.body.classList.add('single');
  const s = document.querySelectorAll('.slide')[n - 1]; if (s) s.classList.add('show'); }
"""


def split_slides(md: str):
    parts = [p.strip() for p in re.split(r"\n---\n", md) if p.strip()]
    slides = []
    for p in parts:
        # El encabezado del documento puede venir pegado a la primera slide: se corta hasta el primer "## "
        m = re.search(r"^## ", p, flags=re.M)
        if not m:
            continue
        p = p[m.start():]
        notes = ""
        m = re.search(r"\*\*Notas del orador:\*\*\s*(.+)$", p, flags=re.S)
        if m:
            notes, p = m.group(1).strip(), p[:m.start()].rstrip()
        title = p.splitlines()[0][3:].strip()
        slides.append((title, p, notes))
    return slides


def render_slide(i: int, total: int, body_md: str) -> str:
    lines = body_md.splitlines()
    head, rest = lines[:2], "\n".join(lines[2:])
    subs = re.findall(r"<sub>.*?</sub>", rest, flags=re.S)
    rest = re.sub(r"<sub>.*?</sub>", "", rest, flags=re.S)
    imgs = re.findall(r"!\[[^\]]*\]\([^)]+\)", rest)
    if not imgs:  # p. ej. el diagrama de arquitectura solo está referido en una línea "Diagrama: ... `charts/x.png`"
        ref = re.search(r"^Diagrama:.*?`(charts/[\w.-]+\.png)`", rest, flags=re.M)
        if ref:
            imgs = [f"![diagrama]({ref.group(1)})"]
    text = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", rest)
    # Líneas meta que solo sirven en el .md ("Gráfico: ...", "Diagrama: ...") no van en la slide
    text = "\n".join(l for l in text.splitlines() if not re.match(r"^(Gráfico|Gráfico de respaldo|Diagrama|Respaldo):", l))
    md = lambda s: markdown.markdown(s, extensions=["tables"])  # noqa: E731
    cols = [f'<div class="col">{md(text)}</div>']
    wide = False
    if imgs:
        src = re.search(r"\(([^)]+)\)", imgs[0]).group(1)
        try:  # imágenes panorámicas (diagramas) a todo el ancho, encima del texto
            from PIL import Image
            w, h = Image.open(os.path.join(PITCH, src)).size
            wide = w / h > 2.2
        except Exception:  # noqa: BLE001
            pass
        cols.insert(0, f'<div class="col{" wide" if wide else ""}">{md(imgs[0])}</div>')
    out = (f'<section class="slide"><div class="num">{i} / {total}</div>{md(chr(10).join(head))}'
           f'<div class="body{" stack" if wide else ""}">{"".join(cols)}</div>{"".join(subs)}</section>')
    return re.sub(r"\[\[PENDIENTE:([^\]]*)\]\]", r'<span class="pending">[[PENDIENTE:\1]]</span>', out)


def build_html() -> str:
    md = open(os.path.join(PITCH, "deck.md"), encoding="utf-8").read()
    slides = split_slides(md)
    body = [render_slide(i, len(slides), s) for i, (_, s, _) in enumerate(slides, 1)]
    notes = "".join(f"<h3>{i}. {html.escape(t)}</h3><p>{html.escape(n)}</p>"
                    for i, (t, _, n) in enumerate(slides, 1) if n)
    if notes:
        body.append(f'<section class="notes"><h2>Notas del orador</h2>{notes}</section>')
    return (f'<!doctype html><html lang="es"><head><meta charset="utf-8"><title>Pitch · Agente de disputas</title>'
            f'<style>{CSS}</style></head><body>{"".join(body)}<script>{JS}</script></body></html>'), len(slides)


def browser() -> str:
    for b in BROWSERS:
        if os.path.exists(b) or shutil.which(b):
            return b
    raise SystemExit("No encontré Chrome/Edge para exportar el PDF.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--shots", action="store_true", help="captura PNG por slide en docs/pitch/screens/deck_NN.png")
    a = ap.parse_args()
    page, n = build_html()
    out_html = os.path.join(PITCH, "deck.html")
    open(out_html, "w", encoding="utf-8").write(page)
    url = "file:///" + out_html.replace("\\", "/")
    b = browser()
    common = [b, "--headless=new", "--disable-gpu", "--no-pdf-header-footer", "--hide-scrollbars"]
    subprocess.run(common + [f"--print-to-pdf={os.path.join(PITCH, 'deck.pdf')}", url], check=True,
                   capture_output=True, timeout=120)
    print(f"-> docs/pitch/deck.html, docs/pitch/deck.pdf ({n} slides + notas)")
    if a.shots:
        shots = os.path.join(PITCH, "screens")
        os.makedirs(shots, exist_ok=True)
        for i in range(1, n + 1):
            png = os.path.join(shots, f"deck_{i:02d}.png")
            subprocess.run(common + ["--window-size=1920,1080", f"--screenshot={png}", f"{url}#s{i}"],
                           check=True, capture_output=True, timeout=120)
        print(f"-> {n} capturas en docs/pitch/screens/")


if __name__ == "__main__":
    main()
