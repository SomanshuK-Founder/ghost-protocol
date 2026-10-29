from functools import lru_cache
from typing import Annotated

from pydantic import field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict
from sqlalchemy.engine import URL


class Settings(BaseSettings):
    app_name: str = "NVIDIA Project API"
    environment: str = "development"
    log_level: str = "INFO"
    database_url: str = ""
    mysql_host: str = "localhost"
    mysql_database: str = "nvidia_app"
    mysql_user: str = "app_user"
    mysql_password: str = "change-me"
    api_bearer_token: str = ""
    cors_origins: Annotated[list[str], NoDecode] = []
    tool_timeout_seconds: float = 3.0

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @property
    def resolved_database_url(self) -> str:
        if self.database_url:
            return self.database_url
        return URL.create(
            "mysql+pymysql",
            username=self.mysql_user,
            password=self.mysql_password,
            host=self.mysql_host,
            port=3306,
            database=self.mysql_database,
        ).render_as_string(hide_password=False)

    @field_validator("tool_timeout_seconds")
    @classmethod
    def timeout_is_reasonable(cls, value: float) -> float:
        if not 0.1 <= value <= 30:
            raise ValueError("TOOL_TIMEOUT_SECONDS must be between 0.1 and 30")
        return value

    @field_validator("cors_origins", mode="before")
    @classmethod
    def split_origins(cls, value):
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
