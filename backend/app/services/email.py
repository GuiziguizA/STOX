"""Service email — stub pour MVP.

Les vrais templates HTML sont délégués à FIN-62.
En dev, les tokens sont loggés ; en prod, brancher Resend/SMTP.
"""
import logging

logger = logging.getLogger("app.email")


async def send_verification_email(email: str, token_hex: str) -> None:
    """Envoie (ou logue) le lien de vérification d'email."""
    logger.info("EMAIL verify %s → token=%s", email, token_hex)


async def send_password_reset_email(email: str, token_hex: str) -> None:
    """Envoie (ou logue) le lien de réinitialisation de mot de passe."""
    logger.info("EMAIL reset %s → token=%s", email, token_hex)


async def send_invite_email(email: str, token_hex: str, invited_by: str | None = None) -> None:
    """Envoie (ou logue) l'invitation à rejoindre l'application."""
    logger.info("EMAIL invite %s → token=%s (by=%s)", email, token_hex, invited_by)
