from concurrent.futures import ThreadPoolExecutor
import json
import logging

import jwt
import pytest
from sqlalchemy import func, select, text
from sqlalchemy.exc import ProgrammingError

from app.models import Project, Tenant


def project(client, company, name="Lançamento do produto"):
    result = client.post("/projects", headers=company["headers"], json={"name": name})
    assert result.status_code == 201, result.text
    return result.json()


def test_project_isolation_on_all_operations(client, companies):
    a, b = companies
    p = project(client, a)
    assert client.get("/projects", headers=b["headers"]).json() == []
    for method, payload in [("GET", None), ("PUT", {"name": "Invasão"}), ("DELETE", None)]:
        response = client.request(method, f"/projects/{p['id']}", headers=b["headers"], json=payload)
        assert response.status_code == 404
    assert client.get(f"/projects/{p['id']}", headers=a["headers"]).json()["name"] == p["name"]


def test_task_isolation_and_project_reference(client, companies):
    a, b = companies
    p = project(client, a)
    result = client.post(f"/projects/{p['id']}/tasks", headers=a["headers"], json={"title": "Preparar apresentação"})
    assert result.status_code == 201
    task = result.json()
    for method, body in [("GET", None), ("PATCH", {"done": True}), ("DELETE", None)]:
        assert client.request(method, f"/tasks/{task['id']}", headers=b["headers"], json=body).status_code == 404
    assert client.get(f"/projects/{p['id']}/tasks", headers=b["headers"]).status_code == 404
    assert client.post(f"/projects/{p['id']}/tasks", headers=b["headers"], json={"title": "Intrusa"}).status_code == 404
    assert client.patch(f"/tasks/{task['id']}", headers=a["headers"], json={"done": True}).json()["done"] is True


def test_cascade_delete(client, companies):
    a = companies[0]
    p = project(client, a)
    task = client.post(f"/projects/{p['id']}/tasks", headers=a["headers"], json={"title": "Revisar"}).json()
    assert client.delete(f"/projects/{p['id']}", headers=a["headers"]).status_code == 204
    assert client.get(f"/tasks/{task['id']}", headers=a["headers"]).status_code == 404


def test_cannot_inject_tenant(client, companies):
    a, b = companies
    result = client.post("/projects", headers=a["headers"], json={"name": "Teste", "tenant_id": b["tenant_id"]})
    assert result.status_code == 422
    p = client.post("/projects", headers={**a["headers"], "X-Tenant-ID": b["tenant_id"]}, json={"name": "Pertence à Aurora"})
    assert p.status_code == 201
    assert client.get(f"/projects/{p.json()['id']}", headers=b["headers"]).status_code == 404


def test_login_and_token_tampering(client, companies):
    a, b = companies
    login = client.post("/auth/login", json={"company_slug": a["slug"], "email": "ADMIN@EXAMPLE.COM", "password": "UmaSenhaBoa123!"})
    assert login.status_code == 200
    assert client.post("/auth/login", json={"company_slug": a["slug"], "email": "admin@example.com", "password": "senha-errada"}).status_code == 401
    claims = jwt.decode(a["access_token"], options={"verify_signature": False})
    claims["tenant"] = b["tenant_id"]
    forged = jwt.encode(claims, "another-secret-that-is-at-least-32-characters", algorithm="HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {forged}"}).status_code == 401
    claims["exp"] = 1
    expired = jwt.encode(claims, client.app.state.settings.jwt_secret, algorithm="HS256")
    assert client.get("/me", headers={"Authorization": f"Bearer {expired}"}).status_code == 401
    assert client.get("/projects").status_code == 401


def test_member_permissions_and_removed_account(client, companies):
    a, b = companies
    response = client.post("/users", headers=a["headers"], json={"email": "membro@example.com", "password": "SenhaDaEquipe123!"})
    assert response.status_code == 201
    member_id = response.json()["id"]
    token = client.post("/auth/login", json={"company_slug": a["slug"], "email": "membro@example.com", "password": "SenhaDaEquipe123!"}).json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    assert client.patch("/subscription", headers=headers, json={"plan": "business"}).status_code == 403
    assert client.post("/users", headers=headers, json={"email": "outro@example.com", "password": "SenhaDaEquipe123!"}).status_code == 403
    assert client.delete(f"/users/{member_id}", headers=b["headers"]).status_code == 404
    assert client.delete(f"/users/{member_id}", headers=a["headers"]).status_code == 204
    assert client.get("/me", headers=headers).status_code == 401


def test_limits_upgrade_and_downgrade(client, companies):
    a = companies[0]
    for n in range(3):
        project(client, a, f"Projeto {n}")
    assert client.post("/projects", headers=a["headers"], json={"name": "Quarto"}).status_code == 409
    assert client.patch("/subscription", headers=a["headers"], json={"plan": "pro"}).status_code == 200
    extra = project(client, a, "Quarto")
    assert client.patch("/subscription", headers=a["headers"], json={"plan": "free"}).status_code == 409
    assert client.delete(f"/projects/{extra['id']}", headers=a["headers"]).status_code == 204
    assert client.patch("/subscription", headers=a["headers"], json={"plan": "free"}).status_code == 200


def test_user_limit_and_unique_email(client, companies):
    a = companies[0]
    data = {"email": "colega@example.com", "password": "SenhaDaEquipe123!"}
    assert client.post("/users", headers=a["headers"], json=data).status_code == 201
    assert client.post("/users", headers=a["headers"], json={**data, "email": "mais@example.com"}).status_code == 409
    client.patch("/subscription", headers=a["headers"], json={"plan": "pro"})
    assert client.post("/users", headers=a["headers"], json=data).status_code == 409


def test_inactive_subscription_can_be_reactivated(client, companies):
    a = companies[0]
    for status in ("expired", "canceled"):
        assert client.patch("/subscription", headers=a["headers"], json={"plan": "free", "status": status}).status_code == 200
        assert client.get("/projects", headers=a["headers"]).status_code == 403
        assert client.get("/subscription", headers=a["headers"]).status_code == 200
        assert client.patch("/subscription", headers=a["headers"], json={"plan": "free", "status": "active"}).status_code == 200


def test_request_quota_and_monthly_reset(client, companies):
    a = companies[0]
    with client.app.state.sessions() as session:
        tenant = session.get(Tenant, a["tenant_id"])
        tenant.requests_used = 99
        session.commit()
    assert client.get("/projects", headers=a["headers"]).status_code == 200
    assert client.get("/projects", headers=a["headers"]).status_code == 429
    assert client.get("/subscription", headers=a["headers"]).json()["usage"]["requests"] == 100
    with client.app.state.sessions() as session:
        tenant = session.get(Tenant, a["tenant_id"])
        tenant.usage_month = "2000-01"
        session.commit()
    assert client.get("/projects", headers=a["headers"]).status_code == 200
    assert client.get("/subscription", headers=a["headers"]).json()["usage"]["requests"] == 1


def test_orm_scope_without_explicit_filter(client, companies):
    a, b = companies
    p = project(client, a)
    with client.app.state.sessions(info={"tenant_id": b["tenant_id"]}) as session:
        assert session.scalar(select(Project).where(Project.id == p["id"])) is None
        with pytest.raises(RuntimeError):
            session.add(Project(tenant_id=a["tenant_id"], name="Intruso", description=""))
            session.flush()
    with client.app.state.sessions() as session:
        with pytest.raises(RuntimeError):
            session.scalars(select(Project)).all()
        with pytest.raises(RuntimeError):
            session.scalar(select(func.count()).select_from(Project))


def test_observability_and_secret_redaction(client, companies, caplog):
    a = companies[0]
    caplog.set_level(logging.INFO, logger="tenantflow.requests")
    response = client.get("/projects", headers=a["headers"])
    assert response.headers["X-Request-ID"]
    log = json.loads(caplog.records[-1].message)
    assert log["tenant_id"] == a["tenant_id"]
    assert a["access_token"] not in caplog.text
    invalid = client.post("/auth/login", json={"password": "SECRET"})
    assert invalid.status_code == 422 and "SECRET" not in invalid.text
    assert client.get("/metrics").status_code == 401
    metrics = client.get("/metrics", headers={"Authorization": "Bearer " + client.app.state.settings.metrics_token})
    assert metrics.status_code == 200
    assert "tenantflow_http_requests_total" in metrics.text
    assert a["tenant_id"] not in metrics.text


def test_duplicate_company_and_password_spaces(client, companies):
    a = companies[0]
    duplicate = client.post("/auth/register", json={"company_name": "Outra empresa", "company_slug": a["slug"],
                             "email": "novo@example.com", "password": "UmaSenhaBoa123!"})
    assert duplicate.status_code == 409
    data = {"email": "espacos@example.com", "password": "  UmaSenhaBoa123!  "}
    assert client.post("/users", headers=a["headers"], json=data).status_code == 201
    assert client.post("/auth/login", json={**data, "company_slug": a["slug"]}).status_code == 200
    assert client.post("/auth/login", json={**data, "password": data["password"].strip(), "company_slug": a["slug"]}).status_code == 401


def test_admin_cannot_remove_own_account(client, companies):
    a = companies[0]
    assert client.delete(f"/users/{a['user']['id']}", headers=a["headers"]).status_code == 409


@pytest.mark.postgres
def test_tenant_context_does_not_leak_between_transactions(client, companies):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Contexto transacional exige PostgreSQL.")
    a = companies[0]
    p = project(client, a)
    with client.app.state.engine.connect() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :id, true)"), {"id": a["tenant_id"]})
        assert connection.scalar(text("SELECT count(*) FROM projects WHERE id=:id"), {"id": p["id"]}) == 1
        connection.commit()
        assert connection.scalar(text("SELECT count(*) FROM projects")) == 0


@pytest.mark.postgres
def test_concurrent_user_limit(client, companies):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Concorrência de usuários exige PostgreSQL.")
    a = companies[0]
    with ThreadPoolExecutor(max_workers=5) as executor:
        statuses = list(executor.map(lambda n: client.post("/users", headers=a["headers"],
                        json={"email": f"user{n}@example.com", "password": "SenhaDaEquipe123!"}).status_code, range(5)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 4


@pytest.mark.postgres
def test_postgres_rls_even_with_raw_sql(client, companies):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Defina TEST_DATABASE_URL para verificar RLS no PostgreSQL real.")
    a, b = companies
    p = project(client, a)
    with client.app.state.engine.connect() as connection:
        assert connection.execute(text("SELECT id FROM projects")).all() == []
        connection.execute(text("SELECT set_config('app.tenant_id', :id, true)"), {"id": b["tenant_id"]})
        assert connection.execute(text("SELECT id FROM projects WHERE id=:id"), {"id": p["id"]}).all() == []
        assert connection.execute(text("UPDATE projects SET name='Intruso' WHERE id=:id"), {"id": p["id"]}).rowcount == 0
        assert connection.execute(text("DELETE FROM projects WHERE id=:id"), {"id": p["id"]}).rowcount == 0
    with client.app.state.engine.begin() as connection:
        connection.execute(text("SELECT set_config('app.tenant_id', :id, true)"), {"id": b["tenant_id"]})
        with pytest.raises(ProgrammingError) as denied:
            connection.execute(text("INSERT INTO projects VALUES ('forged', :tenant, 'Intruso', '')"), {"tenant": a["tenant_id"]})
        assert denied.value.orig.sqlstate == "42501"


@pytest.mark.postgres
def test_concurrent_request_reservations(client, companies):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Concorrência de cotas exige PostgreSQL e bloqueio de linha.")
    a = companies[0]
    with client.app.state.sessions() as session:
        tenant = session.get(Tenant, a["tenant_id"])
        tenant.requests_used = 99
        session.commit()
    with ThreadPoolExecutor(max_workers=8) as executor:
        statuses = list(executor.map(lambda _: client.get("/projects", headers=a["headers"]).status_code, range(8)))
    assert statuses.count(200) == 1
    assert statuses.count(429) == 7


@pytest.mark.postgres
def test_concurrent_project_limit(client, companies):
    if client.app.state.engine.dialect.name != "postgresql":
        pytest.skip("Concorrência de projetos exige PostgreSQL.")
    a = companies[0]
    project(client, a, "Primeiro")
    project(client, a, "Segundo")
    with ThreadPoolExecutor(max_workers=6) as executor:
        statuses = list(executor.map(lambda n: client.post("/projects", headers=a["headers"], json={"name": f"Projeto {n}"}).status_code, range(6)))
    assert statuses.count(201) == 1
    assert statuses.count(409) == 5
