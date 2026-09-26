from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: str | None = Field(default=None, description="Dotted path of the invalid input.")
    message: str


class ErrorBody(BaseModel):
    code: str = Field(description="Stable machine-readable error code.")
    message: str = Field(description="Human-readable description in English.")
    details: list[ErrorDetail] = Field(default_factory=list)
    request_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorBody
