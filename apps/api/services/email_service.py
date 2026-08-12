from __future__ import annotations

import asyncio
import smtplib
from email.message import EmailMessage

from ekoa_config.logging import get_logger
from ekoa_config.settings import get_settings

logger = get_logger("api.services.email")


def _send_sync(to: str, subject: str, html_body: str) -> None:
    settings = get_settings()
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = settings.SMTP_FROM_EMAIL
    message["To"] = to
    message.set_content("This email requires an HTML-capable mail client.")
    message.add_alternative(html_body, subtype="html")

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as smtp:
        if settings.SMTP_USE_TLS:
            smtp.starttls()
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(message)


async def send_email(to: str, subject: str, html_body: str) -> None:
    """Send an HTML email, off the event loop.

    ``smtplib`` is blocking; this is called from async FastAPI route
    handlers, so the send is offloaded via ``asyncio.to_thread`` rather than
    called inline (the same event-loop-blocking mistake Phase 12 found and
    fixed in the AI service). Unlike the Redis cache helpers elsewhere in the
    codebase, a failed send is NOT swallowed here: the caller (invite
    creation) needs to know the invite didn't actually go out.
    """
    try:
        await asyncio.to_thread(_send_sync, to, subject, html_body)
    except Exception:
        logger.exception("email_send_failed", extra={"to": to, "subject": subject})
        raise
