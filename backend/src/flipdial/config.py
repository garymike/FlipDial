"""Settings, read from environment variables prefixed with FLIPDIAL_ or a .env file.

Secrets use SecretStr so they never appear in reprs or logs.
"""

from __future__ import annotations

import ipaddress
import re
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse

from pydantic import Field, PrivateAttr, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


def is_local_host(host: str) -> bool:
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
    web_dir: Path | None = None  # built web app to serve (web/dist)

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

    # Sign-in. none: no sign-in (localhost only). oidc: sign in with your identity provider.
    # proxy: a reverse proxy that already signs people in passes the user in a header.
    auth_mode: Literal["none", "oidc", "proxy"] = "none"
    allow_no_auth: bool = False  # run without sign-in on a non-localhost address anyway
    public_url: str | None = None  # how browsers reach FlipDial, e.g. https://flipdial.home.arpa
    auth_allowed_users: str = ""  # comma-separated emails or subject IDs; empty allows nobody
    oidc_issuer: str | None = None
    oidc_client_id: str | None = None
    oidc_client_secret: SecretStr | None = None
    oidc_scopes: str = "openid email profile"
    session_idle_hours: float = 12.0
    session_max_days: float = 7.0
    proxy_user_header: str = "Remote-User"
    trusted_proxies: str = "127.0.0.1/32,::1/128"  # only these addresses may set the header
    cookie_secure: bool | None = None  # default: on when public_url uses https

    # Updates: check GitHub once a day for a newer published release (sends nothing else)
    update_check: bool = True
    update_repo: str = "garymike/FlipDial"

    # Logging
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    # CardDAV
    carddav_url: str | None = None
    carddav_username: str | None = None
    carddav_password: SecretStr | None = None
    carddav_addressbook: str | None = None  # display name or path; default: the first found
    carddav_verify_tls: bool = True
    carddav_ca_bundle: Path | None = None  # for servers with their own certificate
    vcard_version: Literal["3.0", "4.0"] = "3.0"  # 3.0 works with the widest range of apps

    # Phone sync (docs/sync.md): a second address book on the same server that phones use.
    # Only contacts switched on for the phone are copied there. Empty: phone sync is off.
    phone_addressbook: str | None = None  # display name or path
    phone_check_hour: int = Field(default=3, ge=0, le=23)  # daily check, server local time
    # Extra names FlipDial may be opened by, without sign-in (comma-separated). Addresses
    # (127.0.0.1, 192.168.1.20), localhost and this computer's own name always work.
    allowed_hosts: str = ""
    # The address phones use for the contacts server, when it differs from the one FlipDial
    # uses (FlipDial may reach it by a name that only works inside Docker, say).
    phone_server_url: str | None = None
    # The bundled contacts server's folder (docs/contacts-server.md). When set, the phone
    # setup wizard can create the phone's account itself.
    radicale_dir: Path | None = None
    _carddav_from_file: bool = PrivateAttr(default=False)

    @property
    def carddav_from_file(self) -> bool:
        """Whether the contacts server came from the settings file (not the built-in one)."""
        return self._carddav_from_file

    # Extraction model
    model_backend: Literal["ollama", "openai_compatible"] = "ollama"
    model_url: str = "http://127.0.0.1:11434"
    model_name: str = "qwen3.5:9b"  # vision model; compare others with flipdial eval
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
        self._carddav_from_file = bool(self.carddav_url)
        host = urlparse(self.model_url).hostname or ""
        if not self.allow_remote_model and not is_local_host(host):
            raise ValueError(
                "model_url points outside the local network. Card images would leave your "
                "network. Set FLIPDIAL_ALLOW_REMOTE_MODEL=true only if you intend that."
            )
        if not re.match(r"^[A-Za-z0-9-]+/[A-Za-z0-9._-]+$", self.update_repo):
            raise ValueError("FLIPDIAL_UPDATE_REPO must look like owner/repository")
        self._check_auth()
        return self

    def _check_auth(self) -> None:
        loopback = self.host in {"127.0.0.1", "::1", "localhost"}
        if self.auth_mode == "none" and not loopback and not self.allow_no_auth:
            raise ValueError(
                f"FlipDial is set to listen on {self.host} with no sign-in. Set "
                "FLIPDIAL_AUTH_MODE to oidc or proxy, or set FLIPDIAL_ALLOW_NO_AUTH=true if "
                "the port is only reachable from this machine (for example a container "
                "published on 127.0.0.1)."
            )
        if self.auth_mode == "oidc":
            missing = [
                name
                for name in ("oidc_issuer", "oidc_client_id", "public_url")
                if not getattr(self, name)
            ]
            if missing:
                raise ValueError(
                    "Sign-in needs " + ", ".join(f"FLIPDIAL_{m.upper()}" for m in missing)
                )
            for name in ("oidc_issuer", "public_url"):
                u = urlparse(getattr(self, name))
                if u.scheme != "https" and not (
                    u.scheme == "http" and is_local_host(u.hostname or "")
                ):
                    raise ValueError(f"FLIPDIAL_{name.upper()} must use https")
        if self.auth_mode in ("oidc", "proxy"):
            from ipaddress import ip_network

            try:
                [ip_network(x.strip()) for x in self.trusted_proxies.split(",") if x.strip()]
            except ValueError as exc:
                raise ValueError("FLIPDIAL_TRUSTED_PROXIES must be IP addresses or ranges") from exc
        if self.auth_mode == "oidc" and not self.allowed_users:
            raise ValueError(
                "Set FLIPDIAL_AUTH_ALLOWED_USERS to the emails or subject IDs allowed to sign in"
            )

    @property
    def allowed_users(self) -> set[str]:
        return {x.strip().casefold() for x in self.auth_allowed_users.split(",") if x.strip()}

    @property
    def secure_cookies(self) -> bool:
        if self.cookie_secure is not None:
            return self.cookie_secure
        return bool(self.public_url and self.public_url.startswith("https://"))


def get_settings() -> Settings:
    from flipdial import builtin_server

    return builtin_server.apply(Settings())
