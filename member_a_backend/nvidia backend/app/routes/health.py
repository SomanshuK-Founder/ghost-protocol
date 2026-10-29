from fastapi import APIRouter

from app.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse, response_model_exclude_none=True, summary="Check API liveness")
def health() -> HealthResponse:
    return HealthResponse(status="ok", database=None)
