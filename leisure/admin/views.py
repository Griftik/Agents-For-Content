"""Админка куратора (SQLAdmin, п. 4 F11): модерация событий, статус и уверенность, ручное добавление."""
from __future__ import annotations

import logging
import secrets

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request
from wtforms import FloatField

from leisure import settings
from leisure.db.models import Decision, Digest, Event, Organizer, Profile
from leisure.db.session import engine


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        user, pwd = str(form.get("username", "")), str(form.get("password", ""))
        ok_user = secrets.compare_digest(user.encode(), settings.ADMIN_USER.encode())
        ok_pwd = secrets.compare_digest(pwd.encode(), settings.ADMIN_PASSWORD.encode())
        if ok_user and ok_pwd:
            request.session.update({"admin": True})
            return True
        return False

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin"))


class EventAdmin(ModelView, model=Event):
    name = "Событие"
    name_plural = "События"
    icon = "fa-solid fa-calendar-days"
    column_list = [Event.title, Event.category, Event.kind, Event.city, Event.dates, Event.status, Event.confidence,
                   Event.promoted_until, Event.updated_at]
    column_searchable_list = [Event.title, Event.venue, Event.slug, Event.category]
    column_sortable_list = [Event.title, Event.category, Event.status, Event.confidence, Event.updated_at, Event.created_at]
    column_default_sort = [(Event.updated_at, True)]
    form_excluded_columns = [Event.created_at, Event.updated_at]
    form_overrides = {"lat": FloatField, "lon": FloatField}  # у SQLAdmin нет конвертера для Float
    page_size = 50
    page_size_options = [25, 50, 100]
    save_as = True  # «сохранить как новое» — быстрое ручное добавление по образцу


class OrganizerAdmin(ModelView, model=Organizer):
    name = "Организатор"
    name_plural = "Организаторы"
    icon = "fa-solid fa-building"
    column_list = [Organizer.name, Organizer.contact, Organizer.telegram_user_id, Organizer.created_at]
    form_excluded_columns = [Organizer.created_at, Organizer.updated_at, Organizer.events]


class ProfileAdmin(ModelView, model=Profile):
    name = "Профиль"
    name_plural = "Профили"
    icon = "fa-solid fa-user"
    column_list = [Profile.user_id, Profile.name, Profile.username, Profile.city, Profile.plan, Profile.digest_day,
                   Profile.digest_hour, Profile.active, Profile.onboarded_at, Profile.created_at]
    column_searchable_list = [Profile.name, Profile.username]
    form_excluded_columns = [Profile.created_at, Profile.updated_at, Profile.decisions, Profile.digests]
    can_create = False


class DecisionAdmin(ModelView, model=Decision):
    name = "Решение"
    name_plural = "Решения"
    icon = "fa-solid fa-check"
    column_list = [Decision.user_id, Decision.event_slug, Decision.status, Decision.reason, Decision.day, Decision.rating,
                   Decision.created_at]
    column_default_sort = [(Decision.created_at, True)]
    can_create = False
    can_edit = False


class DigestAdmin(ModelView, model=Digest):
    name = "Дайджест"
    name_plural = "Дайджесты"
    icon = "fa-solid fa-envelope"
    column_list = [Digest.user_id, Digest.weekend_start, Digest.sent_at, Digest.opened, Digest.decisions_count, Digest.created_at]
    column_default_sort = [(Digest.weekend_start, True)]
    can_create = False
    can_edit = False


def mount_admin(app: FastAPI) -> Admin | None:
    """Админка поднимается только с заданным ADMIN_PASSWORD и настоящим SECRET_KEY (подпись cookie сессии)."""
    if not settings.ADMIN_PASSWORD:
        return None
    if settings.SECRET_KEY == settings.DEV_SECRET:
        logging.getLogger("leisure.admin").warning("SECRET_KEY не задан — админка не смонтирована")
        return None
    admin = Admin(app, engine(), title="Досуг · админка", authentication_backend=AdminAuth(secret_key=settings.SECRET_KEY),
                  base_url="/admin")
    for view in (EventAdmin, OrganizerAdmin, ProfileAdmin, DecisionAdmin, DigestAdmin):
        admin.add_view(view)
    return admin
