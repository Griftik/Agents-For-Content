# Планировщик досуга по ценностям и интересам

Сервис, который раз в неделю присылает в Telegram 5–7 событий на выходные, отобранных под ценности
человека, а не под категории афиши, и учится на каждом его ответе.

> **Постановка** — `docs/SPEC.md` (зеркало файла `SPEC-leisure-planner.md` из папки «ИИдосуг» на Google Drive;
> источник правды — Drive). **Прототип** — артефакт «Уикенд в Москве», из него взяты модель данных, формула
> скоринга, обучение и 177 событий seed.

## Что сделано (план работ, недели 1–2 «Ядро») — готово

| Блок | Где | Статус |
|---|---|---|
| Справочники: 13 ценностей, 15 + 4 категории, VALUE_MAP (22 тега), причины, профиль по умолчанию | `core/catalog.py` | ✅ |
| Веса скоринга и обучения в конфиге | `core/scoring.yaml` | ✅ |
| Скоринг `score(event, profile) → {score, why[]}`, продвижение (+8, порог 55) | `core/scoring.py` | ✅ |
| Обучение: веса решений, affinity, learningBonus, «что я узнал о тебе» | `core/affinity.py` | ✅ |
| Рекомендация: 5 слотов уикенда, kindBonus, «на горизонте» (≤2, score ≥ 70), исключения | `core/recommend.py` | ✅ |
| Слоты, уикенд, «бесплатно», время события | `core/timeutil.py` | ✅ |
| Google Календарь, Outlook, .ics, «Отправить другу», текст плана | `core/links.py` | ✅ |
| Модели Event / Profile / Decision / Digest / Organizer, миграция Alembic | `db/`, `alembic.ini` | ✅ |
| Seed из прототипа (177 событий) и загрузчик | `seed/` | ✅ |
| Схема события и RawEvent (pydantic), промпт и клиент LLM-нормализации | `normalize/` | ✅ (клиент не гонялся на реальном ключе) |
| API: события, профиль, решения, превью дайджеста, полный список, план, .ics, справочники | `api/` | ✅ |
| Админка куратора (SQLAdmin): события, профили, решения, дайджесты, организаторы | `admin/views.py` | ✅ |
| Воркер: расписание (ср 22:00, чт 19:00 по tz, сб 09:00, пн 12:00), тексты и кнопки, отправка через aiogram | `worker/` | ✅ код; не проверялся с живым ботом |
| Docker Compose: PostgreSQL 16 + pgvector, Redis, api, worker | `docker-compose.yml`, `Dockerfile` | ✅ не поднимался (в среде разработки нет Docker) |
| Тесты: паритет с прототипом (177 событий × 3 профиля), 10 эталонных пар, affinity, рекомендация, ссылки, seed, API, сообщения | `tests/` | ✅ 95 тестов |

**Паритет с прототипом.** `tests/test_prototype_parity.py` сверяет Python-ядро с эталоном, снятым прогоном
JS-функций прототипа в Node: баллы, объяснения, бонус обучения, слоты, «бесплатно», affinity и состав
рекомендации совпадают по всем 177 событиям для трёх профилей. Единственное осознанное отличие: ценность
«Инновации/новизна» = 0 даёт 0 (по спеке), а не 3 (в JS `||3` подменял ноль).

## Что дальше (по плану работ)

- **Недели 3–4. Бот.** `bot/main.py` на aiogram: онбординг (ценности → интересы с предзаполнением
  `catalog.interests_from_values` → параметры), обработка кнопок `bot/callbacks.py` → `api.services.set_decision`,
  причины «мимо», оценки; проверить рассылку воркера на живом токене.
- **Недели 5–6. Веб** (Mini App): `web/` на Next.js поверх `/api/*`; авторизация через Telegram initData
  (сейчас API закрыт общим `X-API-Key`, этого недостаточно для публичного веба).
- **Недели 7–8. Сбор.** Коллекторы в `collectors/` (интерфейс в `base.py`), дедупликация (pg_trgm уже включён),
  запуск `normalize.llm.normalize_raw` из воркера, модерация в админке.
- Эмбеддинги (pgvector) и векторный скоринг numpy — когда решений > 20 и профилей > 1 000.

## Запуск локально

```bash
# из корня репозитория
python3 -m venv .venv && . .venv/bin/activate
pip install -r leisure/requirements.txt
cp leisure/.env.example leisure/.env          # DATABASE_URL, ADMIN_PASSWORD, API_KEY …

# PostgreSQL 16: роль leisure/leisure и база leisure (или DATABASE_URL на свою)
alembic -c leisure/alembic.ini upgrade head   # схема
python -m leisure.seed.load                   # 177 событий из прототипа (upsert по slug)

uvicorn leisure.api.main:app --reload         # http://localhost:8000/docs, админка /admin
python -m leisure.worker.schedules            # расписание рассылок (без LEISURE_BOT_TOKEN — только логи)

cd leisure && python -m pytest                # тесты; test_api.py пропускается без БД
```

Через Docker (на VPS): `cd leisure && docker compose up -d --build` — api сам применяет миграции;
seed: `docker compose exec api python -m leisure.seed.load`.

## API (кратко)

| Метод | Путь | Что |
|---|---|---|
| GET | `/api/catalog` | ценности, категории, теги, причины, профиль по умолчанию — для онбординга |
| GET | `/api/events?today=&day=&category=&free=&horizon=` | опубликованные события с будущими датами |
| GET | `/api/events/{slug}`, `/api/events/{slug}/ics?day=` | публичная карточка, файл календаря |
| GET/PUT | `/api/profile/{user_id}` | профиль; PUT — частичное обновление, `consent: true` фиксирует согласие |
| POST/DELETE | `/api/decisions` | решение иду / может / интересно / мимо (+ причина, день, оценка); пересчитывает affinity |
| GET | `/api/digest/{user_id}/preview?today=` | 5 слотов + «на горизонте», с причинами и ссылками календарей |
| GET | `/api/digest/{user_id}/all?today=` | все события с баллом — для веба с фильтрами |
| GET | `/api/plan/{user_id}?today=` | план по дням, конфликты по времени, текст для копирования |

Маршруты профиля, решений и дайджеста требуют заголовок `X-API-Key`, если задан `API_KEY`.

## Решения и отступления от текста спеки

- `Event.note` и `Event.rating` добавлены (были в прототипе, нужны куратору); `geo point` → `lat`/`lon`;
  `embedding vector(1024)` отложен до второго этапа (отдельная миграция, образ `pgvector/pgvector:pg16` уже в compose).
- `Decision.event_slug` в снимке, `Profile.name/username/consent_at/onboarded_at/active` — минимум для 152-ФЗ и рассылки.
- `digest_day` — ISO-день недели (4 = четверг), `digest_hour` — по `Profile.tz`.
- Enum'ы хранятся как `varchar` + CHECK, чтобы расширять справочники без `ALTER TYPE`.
- Синхронный SQLAlchemy: бот будет ходить в сервисный слой через `asyncio.to_thread`, нагрузка MVP это позволяет.
- Служебный тег `камерно` оставлен в справочнике тегов (так размечен seed), хотя дублирует `crowd`.
