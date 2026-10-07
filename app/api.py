from contextlib import asynccontextmanager
from datetime import datetime, timezone
import json
import logging
import secrets
import time
from uuid import uuid4

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt
from prometheus_client import CollectorRegistry, Counter, Histogram, CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError

from .config import Settings
from .database import database
from .models import Project, Task, Tenant, User, identifier
from .plans import PLANS
from .schemas import Login, ProjectCreate, Register, SubscriptionUpdate, TaskCreate, TaskUpdate, UserCreate
from .security import decode_token, hasher, token_for, verify_password

logger = logging.getLogger("tenantflow.requests")
bearer = HTTPBearer(auto_error=False)


def create_app(settings: Settings):
    engine, sessions = database(settings)
    registry = CollectorRegistry()
    requests = Counter("tenantflow_http_requests_total", "Respostas HTTP", ["method", "route", "status"], registry=registry)
    latency = Histogram("tenantflow_http_request_seconds", "Tempo de resposta", ["method", "route"], registry=registry)

    @asynccontextmanager
    async def lifespan(app):
        # O usuário da API não pode ser dono das tabelas nem ignorar RLS.
        if engine.dialect.name == "postgresql":
            with engine.connect() as connection:
                unsafe = connection.scalar(text("""
                    SELECT rolsuper OR rolbypassrls FROM pg_roles WHERE rolname = current_user
                """))
                protected = connection.scalar(text("""
                    SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
                    WHERE n.nspname='public' AND c.relname IN ('users','projects','tasks')
                    AND c.relrowsecurity AND c.relforcerowsecurity
                    AND c.relowner <> (SELECT oid FROM pg_roles WHERE rolname=current_user)
                    AND EXISTS (SELECT 1 FROM pg_policy p WHERE p.polrelid=c.oid)
                """))
                if unsafe or protected != 3:
                    raise RuntimeError("Banco sem isolamento válido. Aplique as migrações e use a conta tenantflow.")
        yield
        engine.dispose()

    app = FastAPI(title="TenantFlow", version="1.0.0", lifespan=lifespan,
                  description="Projetos e tarefas para equipes de diferentes empresas. Cada empresa tem seu espaço e seu plano.")
    app.state.sessions = sessions
    app.state.engine = engine
    app.state.settings = settings

    @app.exception_handler(RequestValidationError)
    async def invalid_input(request, exc):
        errors = [{"field": ".".join(str(part) for part in error["loc"]), "type": error["type"]} for error in exc.errors()]
        return JSONResponse(status_code=422, content={"detail": "Confira os campos enviados.", "errors": errors})

    @app.middleware("http")
    async def observe(request: Request, call_next):
        request_id = str(uuid4())
        request.state.request_id = request_id
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Não incluir corpo, SQL, tokens ou detalhes de exceções no log público.
            response = JSONResponse(status_code=500, content={"detail": "Não foi possível concluir o pedido. Tente novamente.", "request_id": request_id})
        elapsed = time.perf_counter() - started
        route = getattr(request.scope.get("route"), "path", "unmatched")
        requests.labels(request.method, route, str(response.status_code)).inc()
        latency.labels(request.method, route).observe(elapsed)
        logger.info(json.dumps({"event": "http_request", "request_id": request_id, "method": request.method,
                                "route": route, "status": response.status_code, "duration_ms": round(elapsed * 1000, 2),
                                "tenant_id": getattr(request.state, "tenant_id", None)}, ensure_ascii=False))
        response.headers["X-Request-ID"] = request_id
        return response

    def context(request: Request, credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials:
            raise HTTPException(401, "Entre na sua conta para continuar.", headers={"WWW-Authenticate": "Bearer"})
        try:
            claims = decode_token(credentials.credentials, settings)
            if not isinstance(claims["tenant"], str) or not isinstance(claims["sub"], str):
                raise jwt.InvalidTokenError()
        except jwt.InvalidTokenError:
            raise HTTPException(401, "Sua sessão expirou ou é inválida. Faça login novamente.", headers={"WWW-Authenticate": "Bearer"})
        with sessions(info={"tenant_id": claims["tenant"]}) as session:
            user = session.scalar(select(User).where(User.id == claims["sub"]))
            if not user:
                raise HTTPException(401, "Esta conta não está mais disponível.")
            request.state.tenant_id = user.tenant_id
            try:
                yield session, user
                session.commit()
            except BaseException:
                session.rollback()
                raise

    def admin(ctx=Depends(context, scope="function")):
        if ctx[1].role != "admin":
            raise HTTPException(403, "Esta ação precisa de um administrador da empresa.")
        return ctx

    def lock_tenant(session, user):
        return session.scalar(select(Tenant).where(Tenant.id == user.tenant_id)
                              .with_for_update().execution_options(populate_existing=True))

    def paid_context(ctx=Depends(context, scope="function")):
        session, user = ctx
        # A reserva da requisição é confirmada antes do trabalho: inclusive 404 consome cota.
        # O UPDATE e o bloqueio de linha serializam a cota entre processos da API.
        tenant = lock_tenant(session, user)
        if tenant.status != "active":
            raise HTTPException(403, "A assinatura está inativa. Um administrador pode reativá-la.")
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        if tenant.usage_month != month:
            tenant.usage_month, tenant.requests_used = month, 0
        if tenant.requests_used >= PLANS[tenant.plan]["requests_per_month"]:
            raise HTTPException(429, "Sua empresa atingiu o limite de requisições deste mês.")
        tenant.requests_used += 1
        session.commit()
        return ctx

    def item(session, model, item_id):
        result = session.scalar(select(model).where(model.id == item_id))
        if result is None:
            raise HTTPException(404, "Não encontramos este recurso na sua empresa.")
        return result

    def user_view(user):
        return {"id": user.id, "email": user.email, "role": user.role}

    def project_view(project):
        return {"id": project.id, "name": project.name, "description": project.description}

    def task_view(task):
        return {"id": task.id, "project_id": task.project_id, "title": task.title, "done": task.done}

    @app.get("/health", tags=["Serviço"])
    def health():
        try:
            with engine.connect() as connection:
                connection.execute(text("SELECT 1"))
        except Exception:
            raise HTTPException(503, "O banco está indisponível no momento.")
        return {"status": "ok"}

    @app.get("/metrics", tags=["Serviço"], include_in_schema=False)
    def metrics(credentials: HTTPAuthorizationCredentials | None = Depends(bearer)):
        if not credentials or not secrets.compare_digest(credentials.credentials, settings.metrics_token):
            raise HTTPException(401, "Credencial de monitoramento inválida.")
        return Response(generate_latest(registry), media_type=CONTENT_TYPE_LATEST)

    @app.get("/plans", tags=["Planos"])
    def plans():
        return PLANS

    @app.post("/auth/register", status_code=201, tags=["Acesso"])
    def register(data: Register):
        with sessions() as session:
            tenant = Tenant(id=identifier(), name=data.company_name, slug=data.company_slug)
            session.add(tenant)
            try:
                session.flush()
                # A transação já começou antes da empresa existir; aplicar contexto local também aqui.
                session.info["tenant_id"] = tenant.id
                if engine.dialect.name == "postgresql":
                    session.execute(text("SELECT set_config('app.tenant_id', :id, true)"), {"id": tenant.id})
                user = User(tenant_id=tenant.id, email=data.email, password_hash=hasher.hash(data.password), role="admin")
                session.add(user)
                session.commit()
            except IntegrityError:
                session.rollback()
                raise HTTPException(409, "Este identificador de empresa já está em uso. Escolha outro.")
            return {"tenant_id": tenant.id, "user": user_view(user), "access_token": token_for(user, settings), "token_type": "bearer"}

    @app.post("/auth/login", tags=["Acesso"])
    def login(data: Login):
        with sessions() as lookup:
            tenant_id = lookup.scalar(select(Tenant.id).where(Tenant.slug == data.company_slug))
        with sessions(info={"tenant_id": tenant_id or "unknown"}) as session:
            user = session.scalar(select(User).where(User.email == data.email)) if tenant_id else None
            valid = verify_password(data.password, user.password_hash if user else None)
            if not user or not valid:
                raise HTTPException(401, "Empresa, e-mail ou senha não conferem.")
            return {"access_token": token_for(user, settings), "token_type": "bearer"}

    @app.get("/me", tags=["Acesso"])
    def me(ctx=Depends(context, scope="function")):
        session, user = ctx
        tenant = session.get(Tenant, user.tenant_id)
        return {"user": user_view(user), "company": {"id": tenant.id, "name": tenant.name, "slug": tenant.slug}}

    @app.get("/subscription", tags=["Planos"])
    def subscription(ctx=Depends(context, scope="function")):
        session, user = ctx
        tenant = session.get(Tenant, user.tenant_id)
        month = datetime.now(timezone.utc).strftime("%Y-%m")
        return {"plan": tenant.plan, "status": tenant.status, "limits": PLANS[tenant.plan],
                "usage": {"month": month, "requests": tenant.requests_used if tenant.usage_month == month else 0,
                          "users": session.scalar(select(func.count()).select_from(User)),
                          "projects": session.scalar(select(func.count()).select_from(Project))},
                "billing_mode": "simulated"}

    @app.patch("/subscription", tags=["Planos"])
    def update_subscription(data: SubscriptionUpdate, ctx=Depends(admin)):
        session, user = ctx
        tenant = lock_tenant(session, user)
        limits = PLANS[data.plan]
        users = session.scalar(select(func.count()).select_from(User))
        projects = session.scalar(select(func.count()).select_from(Project))
        if users > limits["users"] or projects > limits["projects"]:
            raise HTTPException(409, "Remova usuários ou projetos excedentes antes de mudar para este plano.")
        tenant.plan, tenant.status = data.plan, data.status
        return {"plan": tenant.plan, "status": tenant.status, "billing_mode": "simulated"}

    @app.get("/users", tags=["Equipe"])
    def list_users(ctx=Depends(context, scope="function"), offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Use offset a partir de zero e limit entre 1 e 100.")
        return [user_view(u) for u in ctx[0].scalars(select(User).order_by(User.id).offset(offset).limit(limit))]

    @app.post("/users", status_code=201, tags=["Equipe"])
    def create_user(data: UserCreate, ctx=Depends(admin)):
        session, current = ctx
        tenant = lock_tenant(session, current)
        if tenant.status != "active":
            raise HTTPException(403, "Reative a assinatura para adicionar pessoas à equipe.")
        if session.scalar(select(func.count()).select_from(User)) >= PLANS[tenant.plan]["users"]:
            raise HTTPException(409, "Seu plano chegou ao limite de usuários.")
        user = User(tenant_id=current.tenant_id, email=data.email, password_hash=hasher.hash(data.password), role=data.role)
        session.add(user)
        try:
            session.flush()
        except IntegrityError:
            raise HTTPException(409, "Este e-mail já faz parte da sua empresa.")
        return user_view(user)

    @app.delete("/users/{user_id}", status_code=204, tags=["Equipe"])
    def remove_user(user_id: str, ctx=Depends(admin)):
        session, current = ctx
        lock_tenant(session, current)
        user = item(session, User, user_id)
        if user.id == current.id:
            raise HTTPException(409, "Peça a outro administrador para remover sua conta.")
        session.delete(user)
        return Response(status_code=204)

    @app.get("/projects", tags=["Projetos"])
    def list_projects(ctx=Depends(paid_context), offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Use offset a partir de zero e limit entre 1 e 100.")
        return [project_view(p) for p in ctx[0].scalars(select(Project).order_by(Project.id).offset(offset).limit(limit))]

    @app.post("/projects", status_code=201, tags=["Projetos"])
    def create_project(data: ProjectCreate, ctx=Depends(paid_context)):
        session, user = ctx
        tenant = lock_tenant(session, user)
        if tenant.status != "active":
            raise HTTPException(403, "A assinatura está inativa.")
        if session.scalar(select(func.count()).select_from(Project)) >= PLANS[tenant.plan]["projects"]:
            raise HTTPException(409, "Seu plano chegou ao limite de projetos.")
        project = Project(tenant_id=user.tenant_id, **data.model_dump())
        session.add(project)
        session.flush()
        return project_view(project)

    @app.get("/projects/{project_id}", tags=["Projetos"])
    def get_project(project_id: str, ctx=Depends(paid_context)):
        return project_view(item(ctx[0], Project, project_id))

    @app.put("/projects/{project_id}", tags=["Projetos"])
    def update_project(project_id: str, data: ProjectCreate, ctx=Depends(paid_context)):
        project = item(ctx[0], Project, project_id)
        project.name, project.description = data.name, data.description
        return project_view(project)

    @app.delete("/projects/{project_id}", status_code=204, tags=["Projetos"])
    def remove_project(project_id: str, ctx=Depends(paid_context)):
        session, user = ctx
        lock_tenant(session, user)
        session.delete(item(session, Project, project_id))
        return Response(status_code=204)

    @app.get("/projects/{project_id}/tasks", tags=["Tarefas"])
    def list_tasks(project_id: str, ctx=Depends(paid_context), offset: int = 0, limit: int = 50):
        if offset < 0 or not 1 <= limit <= 100:
            raise HTTPException(422, "Use offset a partir de zero e limit entre 1 e 100.")
        session = ctx[0]
        item(session, Project, project_id)
        return [task_view(t) for t in session.scalars(select(Task).where(Task.project_id == project_id).order_by(Task.id).offset(offset).limit(limit))]

    @app.post("/projects/{project_id}/tasks", status_code=201, tags=["Tarefas"])
    def create_task(project_id: str, data: TaskCreate, ctx=Depends(paid_context)):
        session, user = ctx
        item(session, Project, project_id)
        task = Task(tenant_id=user.tenant_id, project_id=project_id, title=data.title)
        session.add(task)
        session.flush()
        return task_view(task)

    @app.get("/tasks/{task_id}", tags=["Tarefas"])
    def get_task(task_id: str, ctx=Depends(paid_context)):
        return task_view(item(ctx[0], Task, task_id))

    @app.patch("/tasks/{task_id}", tags=["Tarefas"])
    def update_task(task_id: str, data: TaskUpdate, ctx=Depends(paid_context)):
        task = item(ctx[0], Task, task_id)
        for key, value in data.model_dump(exclude_unset=True).items():
            if value is None:
                raise HTTPException(422, "Os campos da tarefa não podem ser nulos.")
            setattr(task, key, value)
        return task_view(task)

    @app.delete("/tasks/{task_id}", status_code=204, tags=["Tarefas"])
    def remove_task(task_id: str, ctx=Depends(paid_context)):
        ctx[0].delete(item(ctx[0], Task, task_id))
        return Response(status_code=204)

    return app
