from typing import Annotated

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


_INSECURE_DEFAULTS = {
    "postgres_password": "changeme",
    "secret_key": "change_me_with_a_random_32_byte_hex_string",
}


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # PostgreSQL
    postgres_host: str = "db"
    postgres_port: int = 5432
    postgres_db: str = "projet_action"
    postgres_user: str = "postgres"
    postgres_password: str = "changeme"
    database_url: str = ""

    # Redis
    redis_url: str = "redis://cache:6379/0"

    # App
    app_env: str = "development"
    log_level: str = "info"
    secret_key: str = "change_me_with_a_random_32_byte_hex_string"

    # CORS — origines Next.js autorisees (string CSV ou list via .env).
    # Avec nginx en reverse proxy single-origin, le browser appelle toujours
    # http://localhost (port 80), donc une seule origine suffit en dev.
    # NoDecode : empeche pydantic-settings 2.x de tenter un json.loads sur la
    # valeur env brute (ex: "http://localhost"), ce qui laisse le validator
    # _parse_cors_origins ci-dessous gerer le format CSV.
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost"]

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: object) -> list[str]:
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        if isinstance(value, list):
            return value
        raise ValueError("cors_origins doit être une liste ou une chaîne CSV")

    # Session cookie
    session_cookie_name: str = "cc_session"
    session_max_age_seconds: int = 60 * 60 * 24 * 30  # 30 jours
    session_idle_seconds: int = 60 * 60 * 24  # 24h

    # CSRF
    csrf_cookie_name: str = "cc_csrf"
    csrf_header_name: str = "x-csrf-token"

    # Email — Resend
    resend_api_key: str = ""
    email_from: str = "noreply@exemple.fr"
    email_reply_to: str = "support@exemple.fr"

    # Frontend — URL publique (utilisee dans les liens d'email).
    # Single-origin via nginx -> http://localhost (port 80) en dev.
    frontend_url: str = "http://localhost"

    # Cron jobs purge
    cron_secret: str = ""

    @property
    def async_database_url(self) -> str:
        if self.database_url:
            url = self.database_url
            if url.startswith("postgresql://"):
                return url.replace("postgresql://", "postgresql+asyncpg://", 1)
            return url
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @model_validator(mode="after")
    def _validate_production_secrets(self) -> "Settings":
        """En production : refuse les secrets par défaut, les CORS permissifs et les configs vides.

        Raison : un déploiement avec `change_me_*` ou `cron_secret=""` est une faille
        critique. Cette validation au boot fait crasher l'app plutôt que démarrer
        en silence avec une config dangereuse.
        """
        if not self.is_production:
            return self

        problems: list[str] = []
        if self.secret_key == _INSECURE_DEFAULTS["secret_key"]:
            problems.append("secret_key utilise la valeur par défaut")
        if self.postgres_password == _INSECURE_DEFAULTS["postgres_password"]:
            problems.append("postgres_password utilise la valeur par défaut")
        if not self.cron_secret:
            problems.append("cron_secret est vide")
        if not self.resend_api_key:
            problems.append("resend_api_key est vide")
        if not self.cors_origins:
            problems.append("cors_origins est vide")
        if "*" in self.cors_origins:
            problems.append("cors_origins contient '*' (interdit en prod avec credentials=True)")
        non_https = [o for o in self.cors_origins if not o.startswith("https://")]
        if non_https:
            problems.append(f"cors_origins contient des origines non-HTTPS: {non_https}")

        if problems:
            raise RuntimeError(
                "Configuration de production invalide:\n  - " + "\n  - ".join(problems)
            )
        return self


settings = Settings()
