"""Settings, read from environment variables prefixed with FLIPDIAL_ or a .env file.

Secrets use SecretStr so they never appear in reprs or logs.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def _is_local_host(host: str) -> bool:
    """True for loopback, private-network and link-local hosts."""
    if host in {"localhost", ""} or host.endswith((".local", ".lan", ".internal", ".home.arpa")):
        return True
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return ip.is_loopback or ip.is_private or ip.is_link_local


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="FLIPDIAL_", env_file=".env", extra="ignore")

    # Server
    host: str = "127.0.0.1"
    port: int = 8080

    # Storage
    data_dir: Path = Path("./data")
    inbox_dir: Path | None = None
    archive_dir: Path | None = None
    rejected_dir: Path | None = None
    db_path: Path | None = None

    # Ingest
    ingest_mode: Literal["auto", "duplex", "single", "named"] = "auto"
    settle_seconds: float = 5.0  # a file must be unchanged this long before it is read
    pair_timeout_seconds: float = 120.0  # duplex: wait this long for a missing back
    poll_seconds: float = 3.0
    max_file_mb: int = 50
    max_pixels: int = 60_000_000
    max_pdf_pages: int = 50
    auto_crop: bool = True

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # CardDAV
    carddav_url: str | None = None
    carddav_username: str | None = None
    carddav_password: SecretStr | None = None

    # Extraction model
    model_backend: Literal["ollama", "openai_compatible"] = "ollama"
    model_url: str = "http://127.0.0.1:11434"
    model_name: str = "llama3.2-vision"
    model_api_key: SecretStr | None = None
    allow_remote_model: bool = False
    model_timeout_seconds: float = 120.0
    extract_max_attempts: int = 3

    @model_validator(mode="after")
    def _defaults_and_guards(self) -> Settings:
        if self.inbox_dir is None:
            self.inbox_dir = self.data_dir / "inbox"
        if self.archive_dir is None:
            self.archive_dir = self.data_dir / "archive"
        if self.rejected_dir is None:
            self.rejected_dir = self.data_dir / "rejected"
        if self.db_path is None:
            self.db_path = self.data_dir / "flipdial.db"
        host = urlparse(self.model_url).hostname or ""
        if not self.allow_remote_model and not _is_local_host(host):
            raise ValueError(
                "model_url points outside the local network. Card images would leave your "
                "network. Set FLIPDIAL_ALLOW_REMOTE_MODEL=true only if you intend that."
            )
        return self


def get_settings() -> Settings:
    return Settings()
