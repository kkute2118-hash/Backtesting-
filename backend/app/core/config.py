"""Server configuration. Provider credentials are deliberately NOT held here.

Credentials stay where the engine already reads them - the process environment,
via ``core._secret()`` - so there is exactly one lookup path shared by the API
server and the scheduled GitHub Actions jobs. Duplicating them into a settings
object would create a second source of truth that silently disagrees with the
cron runner.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "Adaptive Trading Intelligence Lab"
    api_prefix: str = "/api/v1"
    debug: bool = False

    # Browser origins allowed to call this API.
    cors_origins: str = "http://localhost:3000"

    # How many scans / backtests may run at once. These are CPU-bound pandas
    # workloads over the whole NSE universe; more workers than cores just makes
    # every one of them slower.
    job_workers: int = 2
    # Finished jobs are kept this long so a page reload can still read its result.
    job_retention_minutes: int = 240

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
