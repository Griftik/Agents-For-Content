"""Контракт API приложения, версия 2 (leisure/README.md «Продукт без Telegram (версия 2)», docs/PIVOT-PWA.md).

Рассылок, push и «Входящих» нет: человек сам открывает приложение, лента всегда актуальна. Аккаунт — гостевая сессия; профилей в
аккаунте несколько, основной профиль «я» имеет user_id = id аккаунта, у дополнительных свои user_id; решения привязаны к профилю
(user_id профиля передаётся во все маршруты)."""
from __future__ import annotations

POST_SESSION = "/api/session"                        # → {"user_id": int}; ничего не сохраняет
PUT_PROFILE = "/api/profile/{uid}"                   # первый PUT с consent создаёт аккаунт и профиль; values, interests, params, onboarded, ref_code
GET_PROFILE = "/api/profile/{uid}"
DELETE_PROFILE = "/api/profile/{uid}"                # основной профиль → весь аккаунт; дополнительный → только он
PROFILES = "/api/profiles"                           # GET ?user_id= (все профили аккаунта); POST {user_id, name, kind} → ProfilesOut
DELETE_SUB_PROFILE = "/api/profiles/{pid}"           # ?user_id=
GET_FEED = "/api/feed"                               # ?user_id&date=today|tomorrow|week|YYYY-MM-DD&segment=leisure|business|all&limit; 409 not_onboarded
GET_PLAN = "/api/plan/{uid}"                         # days (7 дней), horizon, past (30 дней, для отметок «сходил / не сходил» и оценки)
POST_DECISION = "/api/decisions"                     # {user_id, event, status, reason?, day?, rating?} → DecisionOut + ref_ask | ask_reason
GET_DECISIONS = "/api/decisions/{uid}"
POST_INVITE = "/api/invites"
GET_INVITE = "/api/invites/{code}"
OPEN_INVITE = "/api/invites/{code}/open"
ACCEPT_INVITE = "/api/invites/{code}/accept"
GET_GROWTH = "/api/metrics/growth"

# Статусы решений: «Иду» и «Не моё» на карточке; после даты события — «сходил / не сходил» (иначе 400) и оценка 1–5.
GO, NOT_MINE, WENT, SKIPPED, MAYBE = "иду", "не моё", "сходил", "не сходил", "может"
SEGMENTS = ("leisure", "business", "all")
DAYS = ("today", "tomorrow", "week")
TOP_N = 5                                            # первая пятёрка ленты: по ней проверяется персональное обучение
