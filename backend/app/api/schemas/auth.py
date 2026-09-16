from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class SignUpRequest(BaseModel):
    username: str = Field(min_length=2, max_length=64)
    email: str = Field(max_length=320)
    password: str = Field(min_length=8, max_length=72)


class SignInRequest(BaseModel):
    # Username or email; the service works out which.
    identifier: str = Field(min_length=1, max_length=320)
    password: str = Field(min_length=1, max_length=72)


class UpdateProfileRequest(BaseModel):
    display_name: str | None = Field(default=None, max_length=120)
    email: str | None = Field(default=None, max_length=320)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(min_length=1, max_length=72)
    new_password: str = Field(min_length=8, max_length=72)


class UserResponse(BaseModel):
    """What the browser is allowed to know about a user. No password hash."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    username: str
    email: str
    display_name: str | None
    is_admin: bool
    created_at: datetime
