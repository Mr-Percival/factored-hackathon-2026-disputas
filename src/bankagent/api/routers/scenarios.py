"""Escenarios de la demo (desde JSON: se cambian sin tocar código)."""
from __future__ import annotations

from fastapi import APIRouter

from ..deps import RuntimeDep
from ..schemas import ScenariosResponse

router = APIRouter(tags=["escenarios"])


@router.get("/scenarios", response_model=ScenariosResponse,
            summary="Escenarios de demo: cliente, mensajes exactos por turno y resultado esperado")
def list_scenarios(rt: RuntimeDep) -> ScenariosResponse:
    return ScenariosResponse(source=rt.scenarios_source, disclaimer=rt.disclaimer, data_source=rt.data_source,
                             allow_any_customer=rt.settings.allow_any_customer, scenarios=rt.scenarios,
                             quick_replies=rt.quick_replies)
