import uuid
from datetime import datetime
from typing import Annotated, Final, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, StringConstraints

from app.models.user import DISPLAY_NAME_MAX_LENGTH

PASSWORD_MIN_LENGTH: Final = 10
PASSWORD_MAX_LENGTH: Final = 128
_LOGIN_PASSWORD_MIN_LENGTH: Final = 1
_DISPLAY_NAME_MIN_LENGTH: Final = 1

DisplayName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=_DISPLAY_NAME_MIN_LENGTH,
        max_length=DISPLAY_NAME_MAX_LENGTH,
    ),
]


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)
    display_name: DisplayName


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=_LOGIN_PASSWORD_MIN_LENGTH, max_length=PASSWORD_MAX_LENGTH)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    display_name: str
    created_at: datetime


class SessionOut(BaseModel):
    user: UserOut
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 -- a token kind label, not a credential
    expires_in: int = Field(description="Access token lifetime in seconds.")


class TokenOut(BaseModel):
    access_token: str
    token_type: Literal["bearer"] = "bearer"  # noqa: S105 -- a token kind label, not a credential
