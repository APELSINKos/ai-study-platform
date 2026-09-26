from http import HTTPStatus

from fastapi import APIRouter, Response

from app.api.deps import DbSession, RedisClient
from app.schemas.health import LivenessResponse, ReadinessResponse
from app.services.health import readiness_report

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", summary="Liveness probe")
def live() -> LivenessResponse:
    return LivenessResponse()


@router.get(
    "/ready",
    summary="Readiness probe",
    responses={HTTPStatus.SERVICE_UNAVAILABLE: {"model": ReadinessResponse}},
)
def ready(response: Response, session: DbSession, redis_client: RedisClient) -> ReadinessResponse:
    report = readiness_report(session, redis_client)
    if report.status != "ok":
        response.status_code = HTTPStatus.SERVICE_UNAVAILABLE
    return report
