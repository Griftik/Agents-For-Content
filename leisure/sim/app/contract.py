"""Контракт API приложения, версия 2 (docs/PIVOT-PWA.md «Версия 2»). ГОТОВО — уже есть в API; ПРЕДПОЛОЖЕНО — по документу, сверить после ТЗ бэкенда.

Рассылок, push и «Входящих» нет: человек сам открывает приложение, лента всегда актуальна. Профилей в аккаунте несколько, решения привязаны к профилю."""
from __future__ import annotations

# ── ГОТОВО ──
POST_INVITE = "/api/invites"
GET_INVITE = "/api/invites/{code}"
OPEN_INVITE = "/api/invites/{code}/open"
ACCEPT_INVITE = "/api/invites/{code}/accept"
GET_GROWTH = "/api/metrics/growth"

# ── ПРЕДПОЛОЖЕНО ──
POST_SESSION = "/api/session"                        # → {"user_id": int, "token": str, "profile_id": int}: гостевой аккаунт с первым профилем «я»
POST_PROFILE = "/api/profiles"                       # {user_id, name, kind: self|parent|child|other} → {"profile_id": int, ...}
PUT_PROFILE = "/api/profiles/{pid}"                  # values, interests, params (в т.ч. budget, travel_minutes), consent, onboarded, ref_code, show_name
GET_PROFILE = "/api/profiles/{pid}"
DELETE_ACCOUNT = "/api/account/{uid}"                # «Удалить мои данные»: аккаунт, профили, решения
GET_FEED = "/api/feed"                               # params: profile_id, date=YYYY-MM-DD|today|tomorrow|week, segment=leisure|business|all, limit
GET_PLAN = "/api/plan/{pid}"                         # по дням; companions у «иду» по приглашениям («вдвоём с Имя»); прошедшие — для отметки
POST_DECISION = "/api/decisions"                     # {user_id, profile_id, event, status, reason?, day?, rating?}

# Статусы решений: «Иду» и «Не моё» на карточке; после даты события — «сходил / не сходил» (went / skipped) и оценка 1–5.
GO, NOT_MINE, WENT, SKIPPED = "иду", "мимо", "went", "skipped"
SEGMENTS = ("leisure", "business", "all")
DAYS = ("today", "tomorrow", "week")
BUSINESS_CATEGORIES_N = 4                            # «business = четыре бизнес-категории каталога»
TOP_N = 5                                            # первая пятёрка ленты: обучение проверяется по ней
