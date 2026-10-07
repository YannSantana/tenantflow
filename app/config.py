from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    database_url: str = "postgresql+psycopg://tenantflow:local-demo-only@localhost:5432/tenantflow"
    jwt_secret: str = Field(min_length=32)
    metrics_token: str = Field(min_length=24)
    token_minutes: int = Field(default=60, ge=1, le=1440)
    allow_sqlite: bool = False
