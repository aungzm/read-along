from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration.

    Every field can be overridden with a ``READ_ALONG_``-prefixed environment
    variable, or from a ``.env`` file beside this service.
    """

    model_config = SettingsConfigDict(
        env_prefix="READ_ALONG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    app_name: str = "read-along API"
    version: str = "0.0.0"
    cors_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    # Where uploaded EPUBs and audiobooks are written, one directory per job.
    data_dir: Path = Path("var")
    # Per-file upload cap. Protects the disk from a runaway client.
    max_upload_bytes: int = 2 * 1024**3


@lru_cache
def get_settings() -> Settings:
    return Settings()
