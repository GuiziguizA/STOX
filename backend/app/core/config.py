from pydantic_settings import BaseSettings, SettingsConfigDict


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

    # CORS — origines Next.js autorisées
    cors_origins: list[str] = ["http://localhost:3000"]

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

    # Frontend
    frontend_url: str = "http://localhost:3000"

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


settings = Settings()
