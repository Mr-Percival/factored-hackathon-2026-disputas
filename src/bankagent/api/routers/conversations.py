"""Conversaciones: cada una es un thread del grafo ligado a la sesión que la creó."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, HTTPException, Path, status

from ..deps import RuntimeDep, SessionDep
from ..schemas import ConversationCreated, ErrorResponse, MessageIn, TurnResult
from ..serializers import turn_result

router = APIRouter(prefix="/conversations", tags=["conversaciones"])

ConversationId = Annotated[str, Path(max_length=64)]


@router.post("", response_model=ConversationCreated, status_code=status.HTTP_201_CREATED,
             summary="Nueva conversación para la sesión actual", responses={401: {"model": ErrorResponse}})
def create_conversation(s: SessionDep, rt: RuntimeDep) -> ConversationCreated:
    return ConversationCreated(conversation_id=rt.new_conversation(s))


@router.post("/{conversation_id}/messages", response_model=TurnResult,
             summary="Envía un mensaje del cliente y devuelve el turno del agente con su traza",
             responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse},
                        422: {"model": ErrorResponse}, 429: {"model": ErrorResponse}})
def send_message(conversation_id: ConversationId, body: MessageIn, s: SessionDep, rt: RuntimeDep) -> TurnResult:
    if not rt.owns(s, conversation_id):
        raise HTTPException(404, detail="conversation_not_found")  # ajena o inexistente: misma respuesta
    if not rt.message_limiter.allow("sid:" + s.sid):
        raise HTTPException(429, detail="rate_limited")
    state = rt.chat(s, conversation_id, body.text)
    return turn_result(conversation_id, state)
