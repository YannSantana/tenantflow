import os
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.api import create_app
from app.config import Settings


@pytest.fixture
def client(tmp_path):
    url = os.environ.get("TEST_DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    settings = Settings(database_url=url, allow_sqlite=url.startswith("sqlite"),
                        jwt_secret="test-secret-with-at-least-thirty-two-characters",
                        metrics_token="test-monitoring-token-at-least-24")
    app = create_app(settings)
    with TestClient(app) as client:
        yield client


@pytest.fixture
def companies(client):
    results = []
    for name in ("Aurora", "Horizonte"):
        slug = f"{name.lower()}-{uuid4().hex[:10]}"
        response = client.post("/auth/register", json={"company_name": name, "company_slug": slug,
                               "email": "admin@example.com", "password": "UmaSenhaBoa123!"})
        assert response.status_code == 201, response.text
        results.append({**response.json(), "slug": slug,
                        "headers": {"Authorization": f"Bearer {response.json()['access_token']}"}})
    return results
