"""Escenarios de la demo (desde JSON: se cambian sin tocar código)."""
from __future__ import annotations

from fastapi import APIRouter

from ..deps import RuntimeDep
from ..schemas import ScenariosResponse

router = APIRouter(tags=["escenarios"])


@router.get("/scenarios", response_model=ScenariosResponse, summary="Clientes de demo, escenarios y ejemplos")
def list_scenarios(rt: RuntimeDep) -> ScenariosResponse:
    sc = rt.scenarios
    return ScenariosResponse(version=sc.version, disclaimer=sc.disclaimer, data_source=rt.data_source,
                             allow_any_customer=rt.settings.allow_any_customer, scenarios=sc.scenarios,
                             quick_replies=sc.quick_replies)
