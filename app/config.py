from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    app_password: str = "changeme"
    secret_key: str = "dev-secret-key-change-in-production"
    servers_base_path: str = "/opt/docker"
    session_max_age: int = 86400  # 24 hours
    app_version: str = "dev"

    model_config = {"env_file": ".env"}


@lru_cache
def get_settings() -> Settings:
    return Settings()
