from collections.abc import AsyncGenerator
from datetime import datetime

from sqlalchemy import DateTime
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    # Toutes les colonnes Python `datetime` sont mappees vers TIMESTAMPTZ.
    # Sans ca, SQLAlchemy mappe vers TIMESTAMP (sans tz) alors que la DB a
    # ete creee en TIMESTAMPTZ via les migrations -> asyncpg crash avec
    # "can't subtract offset-naive and offset-aware datetimes" lors de l'insert
    # d'un datetime aware dans une colonne qu'il croit naive.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }


engine = create_async_engine(
    settings.async_database_url,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
    echo=not settings.is_production,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session
