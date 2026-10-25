"""Привязка почты без пароля (docs/PIVOT-PWA.md §2.2): ссылка-вход на 15 минут, одноразовая. Нужен SMTP владельца."""
import hashlib
import logging
import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from leisure import settings
from leisure.db.models import Account, EmailToken

from .. import mailer, services
from ..deps import get_session, require_api_key, resolve_user_id
from ..schemas import EmailAuthIn, EmailAuthOut

log = logging.getLogger("leisure.auth")
router = APIRouter(prefix="/api/auth", tags=["вход по почте"], dependencies=[Depends(require_api_key)])

TOKEN_TTL = timedelta(minutes=15)
MAX_PER_HOUR = 5              # писем на одну почту и на один аккаунт в час
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]+\.[^@\s]{2,}$")
NOT_READY = "почта подключится позже"


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _norm(email: str) -> str:
    return (email or "").strip().lower()


@router.post("/email")
def request_link(body: EmailAuthIn, x_user_id: str | None = Header(default=None), session: Session = Depends(get_session)) -> dict:
    """Отправить письмо со ссылкой-входом. Без SMTP — 503 «почта подключится позже» (токен не создаётся). Нужен профиль с согласием:
    без него привязывать нечего (409 consent_required). Ответ не говорит, есть ли такая почта в системе."""
    if not mailer.configured():
        raise HTTPException(503, NOT_READY)
    uid = resolve_user_id(body.user_id, x_user_id)
    email = _norm(body.email)
    if not EMAIL_RE.match(email) or len(email) > 254:
        raise HTTPException(422, "почта указана неверно")
    p = services.get_profile(session, uid)
    if p is None or p.consent_at is None:
        raise HTTPException(409, "consent_required")
    since = datetime.now(timezone.utc) - timedelta(hours=1)
    recent = session.scalar(select(func.count()).select_from(EmailToken).where(
        EmailToken.created_at >= since, (EmailToken.email == email) | (EmailToken.account_id == p.account_id)))
    if (recent or 0) >= MAX_PER_HOUR:
        raise HTTPException(429, "слишком часто, попробуй через час")
    token = secrets.token_urlsafe(32)
    row = EmailToken(token_hash=_hash(token), email=email, account_id=p.account_id, expires_at=datetime.now(timezone.utc) + TOKEN_TTL)
    session.add(row)
    session.commit()
    link = f"{settings.WEB_BASE_URL.rstrip('/')}/auth/email?token={token}"
    # TODO-COPY: текст письма временный
    text = f"Чтобы войти в Планировщик досуга на другом устройстве, открой ссылку: {link}\n\nОна действует 15 минут и срабатывает один раз."
    try:
        mailer.send_mail(email, "Вход в Планировщик досуга", text)
    except mailer.MailNotConfigured:
        raise HTTPException(503, NOT_READY)
    except Exception:  # noqa: BLE001
        log.exception("письмо не отправлено")
        session.delete(row)
        session.commit()
        raise HTTPException(502, "не удалось отправить письмо, попробуй позже")
    return {"sent": True, "expires_in": int(TOKEN_TTL.total_seconds())}


@router.get("/email/{token}", response_model=EmailAuthOut)
def confirm_link(token: str, session: Session = Depends(get_session)) -> dict:
    """Подтвердить ссылку. Почта уже у другого аккаунта — вернуть его (moved=true): веб переносит сессию на user_id = id того
    аккаунта (его основной профиль). Иначе почта привязывается к аккаунту, который просил письмо. Ссылка одноразовая: повтор и
    просроченная — 410."""
    row = session.scalar(select(EmailToken).where(EmailToken.token_hash == _hash(token)))
    if row is None:
        raise HTTPException(404, "ссылка не найдена")
    if row.used_at is not None or row.expires_at < datetime.now(timezone.utc):
        raise HTTPException(410, "ссылка устарела, запроси новую")
    row.used_at = datetime.now(timezone.utc)
    existing = session.scalar(select(Account).where(Account.email == row.email))
    if existing is not None and existing.id != row.account_id:
        session.commit()
        return {"user_id": existing.id, "account_id": existing.id, "email": row.email, "moved": True}
    acc = session.get(Account, row.account_id)
    if acc is None:                                   # аккаунт удалили, пока ждали письмо
        session.commit()
        raise HTTPException(410, "ссылка устарела, запроси новую")
    acc.email = row.email
    try:
        session.commit()
    except IntegrityError:                            # почту успели привязать к другому аккаунту
        session.rollback()
        other = session.scalar(select(Account).where(Account.email == row.email))
        if other is None:
            raise HTTPException(409, "не удалось привязать почту")
        return {"user_id": other.id, "account_id": other.id, "email": row.email, "moved": True}
    return {"user_id": acc.id, "account_id": acc.id, "email": row.email, "moved": False}
