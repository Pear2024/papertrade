"""Hypothesis Lab: offline prompt parsing, causal backtesting, paper profile promotion."""
from fastapi import APIRouter, Depends, HTTPException

from app.api.deps import get_current_user
from app.models import User
from app.schemas.hypothesis_lab import (
    HypothesisBacktestRequest,
    HypothesisCreateRequest,
    HypothesisListResponse,
    HypothesisResponse,
)
from app.services import hypothesis_lab

router = APIRouter(prefix="/hypothesis-lab", tags=["hypothesis-lab"])

def _plan(user: User) -> str:
    return getattr(user, "subscription_plan", "free")


@router.get("/access")
def lab_access(current_user: User = Depends(get_current_user)) -> dict:
    return hypothesis_lab.access_status(current_user.id, _plan(current_user))


@router.post("", response_model=HypothesisResponse)
def create_hypothesis(
    body: HypothesisCreateRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = current_user
    try:
        return hypothesis_lab.create_hypothesis(current_user.id, body.prompt, body.name, body.structured_rules)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("", response_model=HypothesisListResponse)
def list_hypotheses(current_user: User = Depends(get_current_user)) -> dict:
    _ = current_user
    return {"items": hypothesis_lab.list_hypotheses(current_user.id)}


@router.post("/{hypothesis_id}/backtest")
async def backtest_hypothesis(
    hypothesis_id: str,
    body: HypothesisBacktestRequest,
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = current_user
    try:
        return await hypothesis_lab.run_backtest(current_user.id, _plan(current_user), hypothesis_id, body.bars)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc


@router.post("/{hypothesis_id}/promote", response_model=HypothesisResponse)
def promote_hypothesis(
    hypothesis_id: str,
    current_user: User = Depends(get_current_user),
) -> dict:
    _ = current_user
    try:
        return hypothesis_lab.promote(current_user.id, _plan(current_user), hypothesis_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
