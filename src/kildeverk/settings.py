from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

from kildeverk import __version__

REPO_URL = "https://github.com/Solvelangseth/kildeverk"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="KILDEVERK_", env_file=".env", extra="ignore")

    cache_path: Path = Path.home() / ".cache" / "kildeverk" / "responses.sqlite"
    contact: str = ""
    """Who upstreams should contact about this client's traffic (an email or URL).
    MET Norway requires one; local installs should set their own."""

    deployment: str = "local"
    """`local` for a personal install, `public` for the hosted service."""

    max_wait_s: float = 5.0
    """How long a call may wait for its upstream's token bucket before giving up."""

    timeout_s: float = 20.0

    frost_client_id: str = ""
    """Client id for MET Norway's Frost API (free at frost.met.no). Without it the
    observation tools answer NOT_CONFIGURED; the forecast tool needs nothing."""

    nve_api_key: str = ""
    """Key for NVE's HydAPI (free at hydapi.nve.no). Without it the water tools answer
    NOT_CONFIGURED."""

    client_limit_per_minute: float = 60
    """Calls per minute one client address may make to a public deployment."""

    client_limit_burst: float = 20

    client_ip_header: str = ""
    """Header a trusted proxy puts the caller's address in, e.g. 'Fly-Client-IP'. Empty means
    the connection's own address. Only set this behind a proxy that overwrites the header."""

    site_dir: Path | None = None
    """A built website to serve at '/' (see `kildeverk site`). Without one, '/' answers JSON."""

    entur_client_name: str = ""
    """Sent to Entur as ET-Client-Name, which it requires in the form
    '<company>-<application>'. Defaults to 'kildeverk-<deployment>'."""

    @property
    def et_client_name(self) -> str:
        return self.entur_client_name or f"kildeverk-{self.deployment}"

    @property
    def user_agent(self) -> str:
        contact = f"; {self.contact}" if self.contact else ""
        return f"kildeverk/{__version__} ({self.deployment}; +{REPO_URL}{contact})"
