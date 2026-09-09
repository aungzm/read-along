from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import Field
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
    max_upload_bytes: int = Field(default=2 * 1024**3, gt=0)
    # Total multipart bytes, including encoding overhead. None derives from the
    # two per-file caps plus one MiB of multipart overhead.
    max_request_bytes: int | None = Field(default=None, gt=0)
    max_concurrent_uploads: int = Field(default=2, gt=0)
    max_concurrent_jobs: int = Field(default=1, gt=0)
    max_pending_jobs: int = Field(default=4, gt=0)
    max_archive_bytes: int = Field(default=512 * 1024**2, gt=0)
    max_archive_entry_bytes: int = Field(default=64 * 1024**2, gt=0)
    max_archive_entries: int = Field(default=10_000, gt=0)

    @property
    def request_body_limit(self) -> int:
        return self.max_request_bytes or 2 * self.max_upload_bytes + 1024**2


@lru_cache
def get_settings() -> Settings:
    return Settings()
