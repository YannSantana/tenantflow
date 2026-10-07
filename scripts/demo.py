"""Uma demonstração pequena, com duas empresas e uma tentativa de acesso cruzado."""
import argparse
from uuid import uuid4
import httpx


def main():
    parser = argparse.ArgumentParser(description="Demonstra o isolamento entre Aurora e Horizonte.")
    parser.add_argument("--url", default="http://localhost:8000")
    args = parser.parse_args()
    suffix = uuid4().hex[:8]
    with httpx.Client(base_url=args.url, timeout=20) as client:
        companies = []
        for name in ("Aurora", "Horizonte"):
            response = client.post("/auth/register", json={
                "company_name": name, "company_slug": f"{name.lower()}-{suffix}",
                "email": "admin@example.com", "password": "SenhaDeDemonstracao123!",
            })
            response.raise_for_status()
            companies.append(response.json())
            print(f"Empresa {name} criada.")
        aurora, horizonte = ({"Authorization": "Bearer " + c["access_token"]} for c in companies)
        response = client.post("/projects", headers=aurora, json={"name": "Novo site da Aurora", "description": "Preparar o lançamento até o fim do mês."})
        response.raise_for_status()
        project = response.json()
        response = client.post(f"/projects/{project['id']}/tasks", headers=aurora, json={"title": "Revisar os textos com a equipe"})
        response.raise_for_status()
        print("A Aurora criou um projeto e uma tarefa.")
        response = client.get(f"/projects/{project['id']}", headers=horizonte)
        if response.status_code != 404:
            raise RuntimeError("A demonstração encontrou uma falha no isolamento.")
        print("A Horizonte tentou abrir o projeto da Aurora: acesso bloqueado (404).")
        response = client.patch("/subscription", headers=aurora, json={"plan": "pro"})
        response.raise_for_status()
        print("A Aurora mudou para o plano Pro, com cobrança simulada.")
        response = client.get("/subscription", headers=aurora)
        response.raise_for_status()
        subscription = response.json()
        print(f"Uso da Aurora: {subscription['usage']['projects']} projeto(s), {subscription['usage']['requests']} requisição(ões).")
        print("Demonstração concluída. As duas empresas continuam no banco para você explorar.")


if __name__ == "__main__":
    main()
