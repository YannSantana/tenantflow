from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Credentials(Input):
    email: str = Field(min_length=3, max_length=254, pattern=r"^[^\s@]+@[^\s@]+\.[^\s@]+$")
    password: Annotated[str, StringConstraints(strip_whitespace=False)] = Field(min_length=10, max_length=128)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value):
        return value.lower()


class Register(Credentials):
    company_name: str = Field(min_length=2, max_length=120)
    company_slug: str = Field(min_length=3, max_length=60, pattern=r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


class Login(Credentials):
    company_slug: str = Field(min_length=3, max_length=60)


class UserCreate(Credentials):
    role: Literal["admin", "member"] = "member"


class ProjectCreate(Input):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=1000)


class TaskCreate(Input):
    title: str = Field(min_length=1, max_length=160)


class TaskUpdate(Input):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    done: bool | None = None


class SubscriptionUpdate(Input):
    plan: Literal["free", "pro", "business"]
    status: Literal["active", "canceled", "expired"] = "active"
