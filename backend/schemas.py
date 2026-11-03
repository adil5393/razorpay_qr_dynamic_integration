import re
from datetime import datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    value = value.strip()
    return value or None


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=1, max_length=200)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    email: str
    name: str
    role: str
    is_active: bool
    created_at: datetime
    last_login_at: Optional[datetime] = None


class UserCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(min_length=3, max_length=255)
    password: str = Field(min_length=8, max_length=128)

    @field_validator("email")
    @classmethod
    def valid_email(cls, v: str) -> str:
        v = v.strip().lower()
        if not EMAIL_RE.match(v):
            raise ValueError("Enter a valid email address")
        return v

    @field_validator("name")
    @classmethod
    def strip_name(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Name is required")
        return v


class UserStatusUpdate(BaseModel):
    is_active: bool


class PasswordReset(BaseModel):
    new_password: str = Field(min_length=8, max_length=128)


class ChangePassword(BaseModel):
    current_password: str = Field(min_length=1, max_length=200)
    new_password: str = Field(min_length=8, max_length=128)


class CollectionCreate(BaseModel):
    amount: Decimal = Field(gt=0, le=Decimal("1000000"), decimal_places=2)
    reference: Optional[str] = Field(default=None, max_length=40)
    customer_name: Optional[str] = Field(default=None, max_length=120)
    description: str = Field(min_length=1, max_length=255)

    @field_validator("reference", "customer_name")
    @classmethod
    def strip_optional(cls, v):
        return _clean(v)

    @field_validator("description")
    @classmethod
    def strip_description(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("Description is required")
        return v
