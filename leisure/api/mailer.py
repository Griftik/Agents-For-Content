"""Письма через SMTP (magic link). Без SMTP_HOST письма не уходят: вызывающий отвечает 503."""
from __future__ import annotations

import smtplib
import ssl
from email.message import EmailMessage

from leisure import settings


class MailNotConfigured(Exception):
    pass


def configured() -> bool:
    return bool(settings.SMTP_HOST)


def send_mail(to: str, subject: str, body: str) -> None:
    """Отправить простое текстовое письмо. MailNotConfigured — SMTP не задан; прочие сбои пробрасываются (OSError, SMTPException)."""
    if not configured():
        raise MailNotConfigured()
    msg = EmailMessage()
    msg["From"] = settings.SMTP_FROM or settings.SMTP_USER or "noreply@localhost"
    msg["To"] = to
    msg["Subject"] = subject
    msg.set_content(body)
    ctx = ssl.create_default_context()
    if settings.SMTP_SSL:
        smtp = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15, context=ctx)
    else:
        smtp = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=15)
    with smtp:
        if not settings.SMTP_SSL:
            try:
                smtp.starttls(context=ctx)
            except smtplib.SMTPNotSupportedError:
                pass
        if settings.SMTP_USER:
            smtp.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        smtp.send_message(msg)
