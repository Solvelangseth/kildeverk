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

    @property
    def user_agent(self) -> str:
        contact = f"; {self.contact}" if self.contact else ""
        return f"kildeverk/{__version__} ({self.deployment}; +{REPO_URL}{contact})"
