from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import CheckConstraint, ForeignKey, ForeignKeyConstraint, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def identifier():
    return str(uuid4())


class Base(DeclarativeBase):
    pass


class Tenant(Base):
    __tablename__ = "tenants"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(120))
    slug: Mapped[str] = mapped_column(String(60), unique=True)
    plan: Mapped[str] = mapped_column(String(20), default="free")
    status: Mapped[str] = mapped_column(String(20), default="active")
    usage_month: Mapped[str] = mapped_column(String(7), default=lambda: datetime.now(timezone.utc).strftime("%Y-%m"))
    requests_used: Mapped[int] = mapped_column(default=0)
    __table_args__ = (
        CheckConstraint("plan IN ('free', 'pro', 'business')"),
        CheckConstraint("status IN ('active', 'canceled', 'expired')"),
        CheckConstraint("requests_used >= 0"),
    )


class TenantOwned:
    tenant_id: Mapped[str] = mapped_column(String(36), ForeignKey("tenants.id"), index=True)


class User(TenantOwned, Base):
    __tablename__ = "users"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    email: Mapped[str] = mapped_column(String(254))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(20), default="member")
    __table_args__ = (
        UniqueConstraint("tenant_id", "email"),
        CheckConstraint("role IN ('admin', 'member')"),
    )


class Project(TenantOwned, Base):
    __tablename__ = "projects"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    name: Mapped[str] = mapped_column(String(120))
    description: Mapped[str] = mapped_column(String(1000), default="")
    __table_args__ = (UniqueConstraint("tenant_id", "id"),)


class Task(TenantOwned, Base):
    __tablename__ = "tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=identifier)
    project_id: Mapped[str] = mapped_column(String(36), index=True)
    title: Mapped[str] = mapped_column(String(160))
    done: Mapped[bool] = mapped_column(default=False)
    __table_args__ = (
        ForeignKeyConstraint(["tenant_id", "project_id"], ["projects.tenant_id", "projects.id"], ondelete="CASCADE"),
    )
