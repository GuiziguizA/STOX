"""Service email — Resend HTTP API + fallback log dev."""
import logging
from enum import Enum

import httpx

from app.core.config import settings

logger = logging.getLogger("app.email")

RESEND_API = "https://api.resend.com/emails"


def _is_dev() -> bool:
    return not settings.is_production or not settings.resend_api_key


async def _send(subject: str, html: str, text: str, to: str) -> None:
    if _is_dev():
        logger.info("EMAIL [dev] to=%s subject=%s", to, subject)
        logger.debug("HTML:\n%s", html)
        return

    payload = {
        "from": settings.email_from,
        "reply_to": settings.email_reply_to,
        "to": [to],
        "subject": subject,
        "html": html,
        "text": text,
    }
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(
            RESEND_API,
            json=payload,
            headers={"Authorization": f"Bearer {settings.resend_api_key}"},
        )
    if resp.status_code >= 400:
        logger.error("Resend error %s: %s", resp.status_code, resp.text)


# ── Templates HTML ────────────────────────────────────────────────────────────

_BASE = """\
<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>
  body{{font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;background:#f4f4f5;margin:0;padding:24px}}
  .card{{background:#fff;border-radius:8px;max-width:520px;margin:0 auto;padding:40px;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
  h1{{font-size:22px;margin:0 0 16px}}
  p{{color:#444;line-height:1.6;margin:0 0 16px}}
  .btn{{display:inline-block;background:#3b82f6;color:#fff!important;text-decoration:none;padding:12px 24px;border-radius:6px;font-weight:600;margin:8px 0 24px}}
  .footer{{font-size:12px;color:#9ca3af;margin-top:32px;border-top:1px solid #e5e7eb;padding-top:16px}}
  .warning{{background:#fef3c7;border:1px solid #fbbf24;border-radius:6px;padding:12px 16px;color:#92400e;margin-bottom:16px}}
  .danger{{background:#fee2e2;border:1px solid #f87171;border-radius:6px;padding:12px 16px;color:#991b1b;margin-bottom:16px}}
</style>
</head>
<body>
<div class="card">
{body}
<div class="footer">
  <p>© STOX — <a href="{frontend_url}/legal/privacy">Politique de confidentialité</a> · <a href="{frontend_url}/legal/terms">CGU</a></p>
  <p>Si vous n'avez pas effectué cette action, ignorez cet email ou contactez <a href="mailto:{reply_to}">{reply_to}</a>.</p>
</div>
</div>
</body>
</html>
"""


def _render(body: str) -> str:
    return _BASE.format(
        body=body,
        frontend_url=settings.frontend_url,
        reply_to=settings.email_reply_to,
    )


def _tpl_verify(link: str) -> tuple[str, str]:
    html = _render(f"""
<h1>Vérifiez votre adresse email</h1>
<p>Merci de vous être inscrit sur STOX. Cliquez sur le bouton ci-dessous pour activer votre compte.</p>
<a class="btn" href="{link}">Vérifier mon email</a>
<p>Ce lien expire dans <strong>24 heures</strong>.</p>
<p>Si le bouton ne fonctionne pas, copiez-collez ce lien dans votre navigateur :<br>
<small>{link}</small></p>
""")
    text = (
        f"Vérifiez votre email\n\n"
        f"Cliquez sur ce lien pour activer votre compte (valable 24h) :\n{link}\n\n"
        f"Si vous n'avez pas créé de compte, ignorez cet email."
    )
    return html, text


def _tpl_reset(link: str) -> tuple[str, str]:
    html = _render(f"""
<h1>Réinitialisation de mot de passe</h1>
<p>Nous avons reçu une demande de réinitialisation de votre mot de passe.</p>
<a class="btn" href="{link}">Réinitialiser mon mot de passe</a>
<p>Ce lien expire dans <strong>1 heure</strong>.</p>
<div class="warning">Si vous n'avez pas demandé cette réinitialisation, votre compte est peut-être compromis. Contactez notre support immédiatement.</div>
""")
    text = (
        f"Réinitialisation de mot de passe\n\n"
        f"Lien (valable 1h) : {link}\n\n"
        f"Si vous n'avez pas fait cette demande, contactez notre support."
    )
    return html, text


def _tpl_welcome(first_name: str | None) -> tuple[str, str]:
    name = first_name or "vous"
    html = _render(f"""
<h1>Bienvenue sur STOX 🎉</h1>
<p>Bonjour {name},</p>
<p>Votre email est confirmé et votre compte est actif. Vous pouvez désormais accéder à toutes les fonctionnalités d'STOX.</p>
<a class="btn" href="{settings.frontend_url}/dashboard">Accéder à mon espace</a>
<p><strong>Pour commencer :</strong></p>
<ul>
  <li>Recherchez une action (ex : AAPL, TTE.PA)</li>
  <li>Consultez les scores financiers</li>
  <li>Explorez les zones de valorisation</li>
</ul>
""")
    text = (
        f"Bienvenue sur STOX !\n\n"
        f"Bonjour {name}, votre compte est actif.\n"
        f"Connectez-vous : {settings.frontend_url}/dashboard"
    )
    return html, text


def _tpl_suspend(reason: str | None) -> tuple[str, str]:
    reason_line = f"<p><strong>Raison :</strong> {reason}</p>" if reason else ""
    html = _render(f"""
<h1>Votre compte a été suspendu</h1>
<div class="warning">Votre accès à STOX a été temporairement suspendu.</div>
{reason_line}
<p>Pour toute question ou contestation, contactez notre équipe support.</p>
<a class="btn" href="mailto:{settings.email_reply_to}">Contacter le support</a>
""")
    text = (
        f"Votre compte STOX a été suspendu.\n"
        + (f"Raison : {reason}\n" if reason else "")
        + f"Contactez le support : {settings.email_reply_to}"
    )
    return html, text


def _tpl_delete(days: int = 30) -> tuple[str, str]:
    html = _render(f"""
<h1>Confirmation de suppression de compte</h1>
<div class="danger">Votre demande de suppression a été prise en compte.</div>
<p>Vos données personnelles seront <strong>définitivement supprimées dans {days} jours</strong>, conformément à nos obligations légales.</p>
<p>Les journaux d'audit liés à votre compte sont conservés 12 mois pour des raisons de sécurité et conformité.</p>
<p>Si vous souhaitez annuler cette suppression dans ce délai, contactez notre support.</p>
<a class="btn" href="mailto:{settings.email_reply_to}">Contacter le support</a>
""")
    text = (
        f"Suppression de compte STOX confirmée.\n\n"
        f"Vos données seront supprimées définitivement dans {days} jours.\n"
        f"Les journaux d'audit sont conservés 12 mois (obligations légales).\n"
        f"Pour annuler : {settings.email_reply_to}"
    )
    return html, text


def _tpl_security_alert(ip: str | None, user_agent: str | None) -> tuple[str, str]:
    ip_line = f"<p><strong>IP :</strong> {ip}</p>" if ip else ""
    ua_line = f"<p><strong>Navigateur :</strong> {user_agent}</p>" if user_agent else ""
    html = _render(f"""
<h1>Nouvelle connexion détectée</h1>
<div class="warning">Une connexion à votre compte a été détectée depuis un appareil ou une localisation inhabituelle.</div>
{ip_line}
{ua_line}
<p>Si c'était vous, vous pouvez ignorer cet email.</p>
<p>Si ce n'était pas vous, changez immédiatement votre mot de passe et révoquez toutes vos sessions.</p>
<a class="btn" href="{settings.frontend_url}/settings/security">Gérer mes sessions</a>
""")
    text = (
        f"Nouvelle connexion STOX détectée.\n"
        + (f"IP : {ip}\n" if ip else "")
        + f"Si ce n'était pas vous : {settings.frontend_url}/settings/security"
    )
    return html, text


# ── API publique ──────────────────────────────────────────────────────────────

async def send_verification_email(email: str, token_hex: str) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token_hex}"
    html, text = _tpl_verify(link)
    await _send("Vérifiez votre adresse email — STOX", html, text, email)


async def send_password_reset_email(email: str, token_hex: str) -> None:
    link = f"{settings.frontend_url}/reset-password?token={token_hex}"
    html, text = _tpl_reset(link)
    await _send("Réinitialisation de mot de passe — STOX", html, text, email)


async def send_welcome_email(email: str, first_name: str | None = None) -> None:
    html, text = _tpl_welcome(first_name)
    await _send("Bienvenue sur STOX !", html, text, email)


async def send_invite_email(email: str, token_hex: str, invited_by: str | None = None) -> None:
    link = f"{settings.frontend_url}/verify-email?token={token_hex}"
    body = f"""
<h1>Vous avez été invité sur STOX</h1>
{"<p>Invitation envoyée par <strong>" + invited_by + "</strong>.</p>" if invited_by else ""}
<a class="btn" href="{link}">Accepter l'invitation</a>
<p>Ce lien expire dans 7 jours.</p>
"""
    html = _render(body)
    text = f"Invitation STOX. Lien (7j) : {link}"
    await _send("Vous avez été invité sur STOX", html, text, email)


async def send_suspension_email(email: str, reason: str | None = None) -> None:
    html, text = _tpl_suspend(reason)
    await _send("Votre compte STOX a été suspendu", html, text, email)


async def send_deletion_email(email: str) -> None:
    html, text = _tpl_delete()
    await _send("Confirmation de suppression de compte — STOX", html, text, email)


async def send_security_alert_email(
    email: str,
    ip: str | None = None,
    user_agent: str | None = None,
) -> None:
    html, text = _tpl_security_alert(ip, user_agent)
    await _send("Nouvelle connexion détectée — STOX", html, text, email)
