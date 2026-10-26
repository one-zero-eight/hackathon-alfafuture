"""Polling and server-side undo; messages enter through the shared /api/chat route."""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field

from backend import feedback_pages, feedback_store, journal, pages

router = APIRouter()


class Undo(BaseModel):
    model_config = ConfigDict(extra="forbid")
    page_version: int = Field(ge=1)
    target_version: int = Field(ge=1)


@router.get("/api/feedback/{operation_id}")
def operation(operation_id: str):
    row = feedback_store.get(operation_id)
    if row is None:
        raise HTTPException(404, "operation not found or expired")
    return row


@router.post("/api/profile/{key}/undo")
def undo(key: str, req: Undo):
    try:
        before, after = feedback_store.undo(key, req.page_version, req.target_version)
    except feedback_store.Missing as error:
        raise HTTPException(404, str(error)) from None
    except feedback_store.Conflict as error:
        raise HTTPException(409, str(error)) from None
    patch, changes = feedback_pages.changes(before, after)
    return {"patch": patch, "page": pages.skeleton(after), "changes": changes,
            "scenario": {"kind": "edit", "reason": "Восстановлена сохранённая версия страницы и пользовательского состояния."}}
