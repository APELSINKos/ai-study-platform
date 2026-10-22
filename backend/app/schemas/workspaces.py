import uuid
from datetime import date, datetime
from typing import Annotated, Final

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    WithJsonSchema,
    field_validator,
)

from app.api.pagination import Page
from app.models.workspace import WORKSPACE_DESCRIPTION_MAX_LENGTH, WORKSPACE_NAME_MAX_LENGTH
from app.schemas.text import reject_nul

_NAME_MIN_LENGTH: Final = 1


def _blank_as_none(value: str | None) -> str | None:
    return value or None


WorkspaceName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True, min_length=_NAME_MIN_LENGTH, max_length=WORKSPACE_NAME_MAX_LENGTH
    ),
    AfterValidator(reject_nul),
]
_DescriptionText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, max_length=WORKSPACE_DESCRIPTION_MAX_LENGTH),
    AfterValidator(reject_nul),
]
# A blank description is stored as no description at all.
WorkspaceDescription = Annotated[_DescriptionText | None, AfterValidator(_blank_as_none)]


class WorkspaceCreateRequest(BaseModel):
    name: WorkspaceName
    description: WorkspaceDescription = None
    exam_date: date | None = None


class WorkspaceUpdateRequest(BaseModel):
    """Only the fields sent change; null clears the description or the exam date."""

    # None only stands for "not sent": the validator below rejects an explicit null, so
    # the documented type is a plain string.
    name: Annotated[
        WorkspaceName | None,
        WithJsonSchema(
            {
                "type": "string",
                "minLength": _NAME_MIN_LENGTH,
                "maxLength": WORKSPACE_NAME_MAX_LENGTH,
            }
        ),
    ] = None
    description: WorkspaceDescription = None
    exam_date: date | None = None

    @field_validator("name")
    @classmethod
    def name_cannot_be_null(cls, value: str | None) -> str | None:
        if value is None:
            raise ValueError("the name can be changed but not removed")
        return value


class WorkspaceStats(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_count: int
    ready_count: int
    processing_count: int = Field(
        description="Documents waiting for, or going through, processing."
    )
    failed_count: int
    estimated_study_minutes: int = Field(description="Summed over ready documents only.")


class WorkspaceOut(BaseModel):
    id: uuid.UUID
    name: str
    description: str | None
    exam_date: date | None
    created_at: datetime
    updated_at: datetime
    stats: WorkspaceStats


class WorkspacePage(Page[WorkspaceOut]):
    pass
