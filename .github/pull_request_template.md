## Qué cambia
<!-- 1–3 frases. Enlaza el issue: Closes #N -->

## Por qué
<!-- Motivo o evidencia. Si es una decisión de diseño, enlaza el ADR. -->

## Cómo se probó
- [ ] `pytest -q` en verde
- [ ] Test nuevo o actualizado para el comportamiento cambiado
- [ ] Probado a mano con `python -m bankagent.chat` (si aplica)

## Checklist
- [ ] Sin secretos, datos de clientes ni PDFs en el diff
- [ ] Transiciones nuevas del grafo declaradas en `EDGES`
- [ ] `docs/architecture.md` / ADR actualizados si cambió el diseño
