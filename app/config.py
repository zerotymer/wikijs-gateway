from enum import Enum
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class GatewayMode(str, Enum):
    read_only = "read_only"
    dry_run = "dry_run"
    write = "write"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    wikijs_graphql_url: str
    wikijs_api_token: str
    wikijs_admin_api_token: str
    gateway_token: str
    gateway_admin_token: str
    gateway_mode: GatewayMode = GatewayMode.dry_run
    default_locale: str = "ko"
    allow_path_prefixes: Annotated[list[str], NoDecode] = Field(default=["/agent", "/draft"])
    audit_dir: str = "/audit"
    render_after_write: bool = False
    batch_max_size: int = 50
    batch_concurrency: int = 10

    @field_validator("allow_path_prefixes", mode="before")
    @classmethod
    def parse_prefixes(cls, v: object) -> list[str]:
        if isinstance(v, str):
            return [p.strip() for p in v.split(",") if p.strip()]
        return v  # type: ignore[return-value]


@lru_cache
def get_settings() -> Settings:
    return Settings()
