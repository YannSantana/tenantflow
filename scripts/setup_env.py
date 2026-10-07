"""Cria segredos locais, sem sobrescrever uma configuração existente."""
from pathlib import Path
import secrets

target = Path(__file__).resolve().parents[1] / ".env"
try:
    with target.open("x", encoding="utf-8") as file:
        file.write(f"JWT_SECRET={secrets.token_urlsafe(48)}\nMETRICS_TOKEN={secrets.token_urlsafe(32)}\n")
    print("Tudo pronto: o arquivo .env foi criado com segredos próprios.")
except FileExistsError:
    print("O arquivo .env já existe. Sua configuração foi mantida.")
