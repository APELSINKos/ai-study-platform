from typing import Literal

from pydantic import BaseModel


class ComponentHealth(BaseModel):
    status: Literal["ok", "error"]
    latency_ms: float | None = None


class LivenessResponse(BaseModel):
    status: Literal["ok"] = "ok"


class ReadinessResponse(BaseModel):
    status: Literal["ok", "unavailable"]
    checks: dict[str, ComponentHealth]
