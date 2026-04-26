import os


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "db")
    port = os.getenv("POSTGRES_PORT", "5432")
    db = os.getenv("POSTGRES_DB", "projet_action")
    user = os.getenv("POSTGRES_USER", "postgres")
    password = os.getenv("POSTGRES_PASSWORD", "changeme")
    return f"postgresql://{user}:{password}@{host}:{port}/{db}"


DATABASE_URL: str = get_database_url()
REDIS_URL: str = os.getenv("REDIS_URL", "redis://cache:6379/0")
APP_ENV: str = os.getenv("APP_ENV", "development")
