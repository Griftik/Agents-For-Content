# Досуг · Mini App (Next.js)

Веб-часть планировщика: Telegram Mini App, она же обычный сайт. Next.js 15 (App Router, TypeScript), без Tailwind:
токены и компоненты в `src/app/globals.css` взяты из `leisure/web/DESIGN.md` и макета `leisure/web/mockup.html`.

## Страницы

| Маршрут | Что | Рендер |
|---|---|---|
| `/digest` | 5 слотов рекомендации + полный список с фильтрами (день, направление, бесплатно, скрыть «мимо») | сервер, читается без JS |
| `/plan` | три колонки по дням, конфликты, календари, «На горизонте», «Скопировать план» | сервер; JS нужен только для копирования |
| `/profile` | ценности, направления, параметры, «Что я узнал о тебе», заметка | сервер + форма (PUT); JS только для живого числа у ползунков |
| `/e/<slug>` | публичная страница события, кнопка «Собрать мне такую подборку» → `t.me/<бот>?start=e_<slug>` | сервер, без входа |
| `/policy` | политика из `leisure/web/POLICY.md` (копируется в `content/policy.md` перед `dev`/`build`) | сервер |
| `/api/events/<slug>/ics?day=` | файл календаря (прокси к API) | route handler |
| `/api/auth/telegram` | обмен initData на cookie сессии | route handler |

Кнопки решений («Иду», «Может быть», «Интересно», «Мимо», причины, день, «Убрать») — обычные `<form>` с server actions:
работают без JS (страница перезагружается), с JS — без перезагрузки.

## Вход

Логинов нет. Mini App получает `initData` от Telegram; клиентский слой (`TelegramBoot`) отправляет его в заголовке
`X-Telegram-Init-Data` на `/api/auth/telegram`. Сервер проверяет подпись HMAC-SHA256 (секрет = `HMAC_SHA256("WebAppData", токен бота)`),
свежесть `auth_date` (не старше суток) и достаёт `user.id`, затем выдаёт подписанный httpOnly-cookie на сутки
(`SameSite=None; Secure; Partitioned` в production, так как в вебе Telegram приложение живёт во фрейме).
Все запросы к API делает только сервер Next.js с `X-API-Key`; ключ в браузер не попадает.

Режим разработки (`NODE_ENV=development`, то есть `npm run dev`): `?dev_user=<telegram id>` без подписи ставит dev-cookie.
В production этот путь выключен и dev-cookie не принимается.

## Переменные окружения

| Переменная | Нужна | Что |
|---|---|---|
| `API_BASE_URL` | да | адрес FastAPI, например `http://localhost:8000` (в compose `http://api:8000`) |
| `API_KEY` | да | значение `API_KEY` из окружения API; уходит заголовком `X-API-Key` только с сервера |
| `LEISURE_BOT_TOKEN` | да | токен бота: проверка подписи initData |
| `NEXT_PUBLIC_BOT_USERNAME` | да | имя бота без `@` для ссылок `t.me/<бот>`; читается на старте, пересборка не нужна |
| `WEB_BASE_URL` | нет | публичный адрес веба для ссылок «Другу»; без неё берётся из заголовков запроса |
| `SESSION_SECRET` | нет | секрет подписи cookie; без него выводится из токена бота |

Шаблон: `.env.example`.

## Локальный запуск

```bash
# 1. API (из корня репозитория)
. .venv/bin/activate && API_KEY=dev-key ADMIN_PASSWORD= uvicorn leisure.api.main:app --port 8000

# 2. Веб (из leisure/webapp)
npm install
cp .env.example .env.local        # впиши LEISURE_BOT_TOKEN и имя бота
npm run dev                       # http://localhost:3000/digest?dev_user=<telegram id>
```

Профиль пользователя создаётся в боте (`/start`) или первым `PUT /api/profile/<id>`; без него страницы покажут экран «Сначала познакомимся».
Для проверки на данных октября 2026 в dev можно добавить `?today=2026-10-23`.

Проверки: `npm run lint`, `npm test` (vitest: подпись initData, устаревший `auth_date`, сессия), `npm run build`.

## Docker

Сервис `web` описан в `leisure/docker-compose.yml` (порт 3000). Контекст сборки — `leisure/` (нужен `web/POLICY.md`):

```bash
cd leisure && docker compose up -d --build web
```

В `leisure/.env` должны быть `API_KEY`, `LEISURE_BOT_TOKEN`, `NEXT_PUBLIC_BOT_USERNAME`; `WEB_BASE_URL` для API и веба должен
указывать на публичный адрес веба (HTTPS), а не на порт API.

## Устройство

- `src/lib/telegram.ts` — проверка initData; `session-token.ts` — cookie сессии; `session.ts` — чтение сессии на сервере.
- `src/lib/api.ts` — клиент API (только сервер, `import "server-only"`).
- `src/app/actions.ts` — server actions: решения, «Убрать», сохранение профиля.
- `src/middleware.ts` — только `?dev_user` в режиме разработки.
- Цвета текста `warn` и `brass` в светлой теме затемнены (`--warn-ink`, `--brass-ink`): токены DESIGN.md дают там 4.40 и 3.96:1.
