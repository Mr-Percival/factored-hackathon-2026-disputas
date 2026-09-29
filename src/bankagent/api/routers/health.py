"""Liveness y readiness (para el HEALTHCHECK del contenedor y la plataforma de deploy)."""
from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from ..deps import RuntimeDep
from ..schemas import Health, Ready

router = APIRouter(tags=["salud"])
log = logging.getLogger("bankagent.api")


@router.get("/healthz", response_model=Health, summary="Liveness: el proceso responde")
def healthz() -> Health:
    return Health(status="ok")


@router.get("/readyz", response_model=Ready, summary="Readiness: base alcanzable y política cargada",
            responses={503: {"model": Ready}})
def readyz(rt: RuntimeDep):
    try:
        ok = rt.ready()
    except Exception as e:  # noqa: BLE001 - cualquier falla = no listo; se registra solo el tipo
        log.warning("readyz failed: %s", type(e).__name__)
        ok = False
    if not ok:
        return JSONResponse(Ready(status="not_ready").model_dump(), status_code=503)
    return Ready(status="ready", policy_version=rt.policy.version, data_source=rt.data_source)
