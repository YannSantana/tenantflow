from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import Session, sessionmaker, with_loader_criteria
from sqlalchemy.pool import StaticPool
from sqlalchemy.sql import visitors

from .models import Base, TenantOwned


class TenantSession(Session):
    """Cada sessão pertence a uma empresa; nenhuma sessão é reaproveitada entre pedidos."""


@event.listens_for(TenantSession, "do_orm_execute")
def scope_queries(state):
    tenant_id = state.session.info.get("tenant_id")
    if state.is_select or state.is_update or state.is_delete:
        if not tenant_id:
            # Consultas de tenants usam o plano de controle; entidades privadas exigem contexto.
            private_tables = {"users", "projects", "tasks"}
            if any(getattr(node, "__visit_name__", "") == "table" and node.name in private_tables
                   for node in visitors.iterate(state.statement)):
                raise RuntimeError("Consulta privada sem empresa definida")
        else:
            state.statement = state.statement.options(with_loader_criteria(
                TenantOwned, lambda model: model.tenant_id == tenant_id, include_aliases=True
            ))


@event.listens_for(TenantSession, "before_flush")
def validate_writes(session, *_):
    for obj in session.new | session.dirty | session.deleted:
        if isinstance(obj, TenantOwned):
            if not session.info.get("tenant_id") or obj.tenant_id != session.info["tenant_id"]:
                raise RuntimeError("Escrita fora da empresa autenticada")


@event.listens_for(TenantSession, "after_begin")
def set_database_tenant(session, transaction, connection):
    if connection.dialect.name == "postgresql":
        connection.execute(text("SELECT set_config('app.tenant_id', :tenant, true)"),
                           {"tenant": session.info.get("tenant_id", "")})


def database(settings):
    sqlite = settings.database_url.startswith("sqlite")
    if sqlite and not settings.allow_sqlite:
        raise RuntimeError("SQLite é permitido apenas no modo de testes locais.")
    options = {"pool_pre_ping": True}
    if sqlite:
        options = {"connect_args": {"check_same_thread": False}}
        if ":memory:" in settings.database_url:
            options["poolclass"] = StaticPool
    engine = create_engine(settings.database_url, **options)
    if sqlite:
        @event.listens_for(engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, class_=TenantSession, expire_on_commit=False)
