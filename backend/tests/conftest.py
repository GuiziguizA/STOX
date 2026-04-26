"""Fixtures pytest pour les tests d'intégration des routes FastAPI.

Prérequis :
  - PostgreSQL disponible (docker compose up -d db)
  - Migrations appliquées (alembic upgrade head)
  - Variable d'environnement DATABASE_URL pointant vers la base de test

Lancement :
  DATABASE_URL=postgresql://postgres:changeme@localhost:5432/projet_action_test \
  REDIS_URL=redis://localhost:6379/1 \
  pytest tests/ -v
"""
import asyncio
import os

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.core.db import Base, get_db
from app.main import app

# ── Base de données de test ───────────────────────────────────────────────────

TEST_DB_URL = os.getenv(
    "DATABASE_URL",
    "postgresql://postgres:changeme@localhost:5432/projet_action",
)

if TEST_DB_URL.startswith("postgresql://"):
    ASYNC_TEST_DB_URL = TEST_DB_URL.replace("postgresql://", "postgresql+asyncpg://", 1)
else:
    ASYNC_TEST_DB_URL = TEST_DB_URL


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    engine = create_async_engine(ASYNC_TEST_DB_URL, echo=False)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(test_engine):
    """Session de test isolée dans une transaction annulée après chaque test."""
    async with test_engine.connect() as conn:
        await conn.begin()
        session_factory = async_sessionmaker(
            bind=conn,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
        async with session_factory() as session:
            yield session
        await conn.rollback()


@pytest_asyncio.fixture(scope="function")
async def client(db_session):
    """Client HTTP async avec override de la session DB."""

    async def override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = override_get_db

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    app.dependency_overrides.pop(get_db, None)


# ── Helpers fixtures ──────────────────────────────────────────────────────────

@pytest_asyncio.fixture
async def admin_user(db_session):
    """Crée un user admin actif avec email vérifié."""
    from app.core.security import hash_password
    from app.models.user import Profile, Role, User, UserRole, UserStatus
    from sqlalchemy import select
    from datetime import datetime, timezone

    email = f"admin-{os.urandom(4).hex()}@test.com"
    user = User(
        email=email,
        password_hash=hash_password("AdminPassword1!"),
        status=UserStatus.active,
        email_verified_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()

    profile = Profile(user_id=user.id, first_name="Admin", last_name="Test")
    db_session.add(profile)

    result = await db_session.execute(select(Role).where(Role.code == "admin"))
    admin_role = result.scalar_one()
    db_session.add(UserRole(user_id=user.id, role_id=admin_role.id))
    await db_session.flush()

    return {"id": user.id, "email": email, "password": "AdminPassword1!"}


@pytest_asyncio.fixture
async def active_user(db_session):
    """Crée un user actif sans rôle particulier."""
    from app.core.security import hash_password
    from app.models.user import Profile, User, UserStatus
    from datetime import datetime, timezone

    email = f"user-{os.urandom(4).hex()}@test.com"
    user = User(
        email=email,
        password_hash=hash_password("UserPassword1!"),
        status=UserStatus.active,
        email_verified_at=datetime.now(timezone.utc),
    )
    db_session.add(user)
    await db_session.flush()
    db_session.add(Profile(user_id=user.id))
    await db_session.flush()

    return {"id": user.id, "email": email, "password": "UserPassword1!"}
