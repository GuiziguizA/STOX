"""Endpoint de purge RGPD — POST /internal/purge (CRON_SECRET requis)

Appelé par Vercel Cron / GitHub Actions avec l'en-tête :
  Authorization: Bearer <CRON_SECRET>

Jobs exécutés :
  - Purge email_verification_tokens expirés > 30 jours
  - Purge password_reset_tokens expirés > 30 jours
  - Purge auth_sessions révoquées > 90 jours
"""
from datetime import datetime, timedelta, timezone
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.models.auth import AuthSession, EmailVerificationToken, PasswordResetToken

router = APIRouter(prefix="/internal", tags=["internal"])


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _verify_cron(authorization: str = Header(default="")) -> None:
    if not settings.cron_secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="CRON_SECRET non configuré",
        )
    expected = f"Bearer {settings.cron_secret}"
    if authorization != expected:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Accès refusé")


@router.post("/purge")
async def run_purge(
    db: Annotated[AsyncSession, Depends(get_db)],
    _auth: Annotated[None, Depends(_verify_cron)],
) -> dict:
    now = _now()

    # Tokens email expirés > 30j
    cutoff_tokens = now - timedelta(days=30)
    r1 = await db.execute(
        delete(EmailVerificationToken).where(
            EmailVerificationToken.expires_at < cutoff_tokens
        )
    )

    # Tokens reset expirés > 30j
    r2 = await db.execute(
        delete(PasswordResetToken).where(
            PasswordResetToken.expires_at < cutoff_tokens
        )
    )

    # Sessions révoquées > 90j
    cutoff_sessions = now - timedelta(days=90)
    r3 = await db.execute(
        delete(AuthSession).where(
            AuthSession.revoked_at.is_not(None),
            AuthSession.revoked_at < cutoff_sessions,
        )
    )

    await db.commit()

    return {
        "ok": True,
        "purged_at": now.isoformat(),
        "email_verification_tokens_deleted": r1.rowcount,
        "password_reset_tokens_deleted": r2.rowcount,
        "sessions_deleted": r3.rowcount,
    }
