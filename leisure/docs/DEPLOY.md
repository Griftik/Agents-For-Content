# Развернуть Catch на сервере с нуля (без опыта)

Инструкция рассчитана на человека, который никогда не администрировал серверы. Делается один раз, занимает около
40 минут. Дальше обновления накатываются сами, а перед каждым обновлением автоматически снимается бэкап базы
(«как в Miru: сначала бэкап, потом накат»; при провале проверки сервер сам откатывается на прошлую версию).

## Что где лежит

| Что | Где |
|---|---|
| Код | `~/Agents-For-Content` (клон репозитория), продукт — папка `leisure/` |
| Секреты сервера | `~/Agents-For-Content/leisure/.env` (права 600, в git не попадает) |
| База PostgreSQL | докер-том `leisure_pgdata` — пересборки его не трогают |
| Сертификаты HTTPS | докер-тома `leisure_caddy_data`, `leisure_caddy_config` |
| Бэкапы | `~/backups/catch-<дата>-<время>-<sha>.sql.gz` (30 последних), `~/backups/LAST_GOOD` — sha последней рабочей версии |
| Скрипты | `leisure/server-setup.sh` (первый запуск), `leisure/deploy.sh` (обновление), `leisure/backup.sh`, `leisure/rollback.sh` |
| Маршруты и HTTPS | `leisure/Caddyfile`: `/api/*` → API (FastAPI :8000), остальное → веб (Next.js :3000); наружу открыт только Caddy (80/443) |
| Автодеплой | `.github/workflows/catch.yml`: тесты → безопасность → `deploy.sh` по SSH |

## Шаг 0. Что понадобится

1. **Сервер (VPS).** Любой провайдер: Timeweb Cloud, Beget, Selectel (в РФ, ~500–900 ₽/мес) или Hetzner. При заказе:
   ОС **Ubuntu 24.04**, конфигурация **2 vCPU, 4 ГБ RAM, 30+ ГБ диска** (сборка веба на 2 ГБ может не пройти).
   Провайдер выдаст **IP-адрес** и **root-пароль**.
2. **Домен** (например `catch.example.ru`). У регистратора создай A-запись `@ → IP сервера` (и `www → IP`, если нужен).
   Без домена всё поднимется по `http://IP`, но установка на экран телефона и cookie сессии требуют HTTPS, так что домен нужен
   до первых пользователей. DNS расходится 10–60 минут — можно заказать домен заранее.
3. **Почта для входа по ссылке** (необязательно): один ящик вида `no-reply@ваш-домен` (Яндекс 360 бесплатно) и пароль
   приложения к нему. Без почты кнопка «войти по почте» в приложении помечена «скоро», всё остальное работает.

## Шаг 1. Подключиться к серверу

- **Windows:** Пуск → «PowerShell». **macOS:** Terminal.

```bash
ssh root@ВАШ_IP
```

При первом подключении ответить `yes`, затем ввести root-пароль. Дальше все команды вводятся в этот терминал
(можно копировать блоками целиком). Если ssh не работает — у провайдера в панели есть «Веб-консоль».

## Шаг 2. Скачать код и запустить автонастройку

```bash
apt update && apt install -y git curl
git clone https://github.com/Griftik/Agents-For-Content.git ~/Agents-For-Content
cd ~/Agents-For-Content && git checkout claude/leisure-planner-core   # или main, когда ветка влита
./leisure/server-setup.sh
```

Если репозиторий приватный, перед `git clone` нужен ключ доступа только на чтение:
`ssh-keygen -t ed25519 -N "" -f ~/.ssh/id_ed25519 -q && cat ~/.ssh/id_ed25519.pub` → напечатанную строку добавить на
GitHub: репозиторий → **Settings → Deploy keys → Add deploy key** (без «Allow write access»), а клонировать по адресу
`git@github.com:Griftik/Agents-For-Content.git`.

Скрипт сам:

1. поставит Docker;
2. спросит домен и секреты и соберёт `leisure/.env` (`Enter` на секретах — сгенерирует случайные; пароль админки напечатает —
   запиши), почту можно пропустить;
3. соберёт и запустит контейнеры `db`, `redis`, `api`, `worker`, `web`, `caddy` (первая сборка 3–6 минут), применит миграции;
4. загрузит seed (177 событий), запишет `~/backups/LAST_GOOD` и снимет первый бэкап;
5. поставит ежедневный бэкап в cron на 04:00;
6. подготовит ключ для автодеплоя и напечатает шпаргалку для GitHub.

## Шаг 3. Проверить, что всё живо

```bash
cd ~/Agents-For-Content && ./leisure/deploy.sh --check      # «ок: api и web живы»
cd leisure && docker compose ps                              # все сервисы Up (healthy)
```

Открой `https://ваш-домен` — первый экран с согласием → пять ценностей → направления → лента. Админка: `https://ваш-домен/admin`
(логин и пароль из `leisure/.env`). Если домен ещё не разошёлся, Caddy получит сертификат сам, как только A-запись заработает;
до этого сайт доступен по `http://IP`.

Логи: `cd ~/Agents-For-Content/leisure && docker compose logs -f api web caddy` (выход — `Ctrl+C`).

## Шаг 4. Включить автодеплой на GitHub

Открой репозиторий → **Settings → Secrets and variables → Actions** и перенеси то, что напечатал скрипт:

- вкладка **Secrets** → New repository secret, три штуки: `DEPLOY_HOST` (IP сервера), `DEPLOY_USER` (`root`),
  `DEPLOY_SSH_KEY` (приватный ключ целиком, с строками BEGIN/END);
- вкладка **Variables** → New repository variable: `DEPLOY_ENABLED` = `true`.

Теперь каждый push в `main` или `claude/leisure-planner-core`, задевающий `leisure/**`, проходит через `.github/workflows/catch.yml`:
**test** (PostgreSQL 16, миграции, seed, `pytest`, сборка и vitest веба) и **security** (bandit medium+, pip-audit, `npm audit`
high+) → только зелёный код уезжает на сервер: job **deploy** по SSH запускает `./leisure/deploy.sh`. Пока `DEPLOY_ENABLED` не
задана, шаг деплоя пропускается. Статус — вкладка **Actions**.

## Обновление: что делает `deploy.sh`

```bash
cd ~/Agents-For-Content && ./leisure/deploy.sh
```

1. `git pull --ff-only` своей ветки.
2. **Бэкап перед накатом:** `pg_dump` базы из контейнера `db` → `~/backups/catch-<дата>-<время>-<sha работающей версии>.sql.gz`,
   sha работающей версии → `~/backups/LAST_GOOD`.
3. `docker compose up -d --build` (пересборка только изменившихся образов).
4. `alembic upgrade head` в контейнере `api` (повторно безвредно).
5. Проверка живости до 2 минут: `/api/health` у API, `/api/health` и `/` у веба; через домен — предупреждение, если не отвечает.
6. Успех → sha новой версии в `LAST_GOOD`, старые бэкапы чистятся (хранятся 30). **Провал → автоматический откат:** код на
   `LAST_GOOD`, пересборка, восстановление снятого дампа, повторная проверка; скрипт завершается с ошибкой, в Actions это видно.

Простой при обновлении — 20–60 секунд на пересборку и перезапуск `api`/`web`; база и сертификаты не трогаются.

## Бэкапы

- **Автоматически:** ежедневно в 04:00 (строка в `crontab -l`: `cd ~/Agents-For-Content && ./leisure/backup.sh >> ~/backups/backup.log`)
  и перед каждым обновлением (`deploy.sh`). Хранится 30 последних файлов.
- **Вручную:** `./leisure/backup.sh [метка]`.
- **Скачать копию себе** (раз в неделю или перед рискованными изменениями), с своего компьютера:

```bash
mkdir -p ~/catch-backups
scp root@ВАШ_IP:~/backups/catch-*.sql.gz ~/catch-backups/      # все; или один файл по имени
```

- **Восстановить базу из бэкапа** (код не трогая): `./leisure/rollback.sh catch-20261025-040000-006de78.sql.gz --db-only`.
  Перед восстановлением скрипт снимает страховочный бэкап `catch-…-pre-rollback.sql.gz`.

## Откат вручную

```bash
cd ~/Agents-For-Content
./leisure/rollback.sh                      # список бэкапов, новые сверху
./leisure/rollback.sh latest               # код на sha из имени файла (или LAST_GOOD), пересборка, восстановление базы
./leisure/rollback.sh <файл> --sha abc1234 # явно указать, на какой коммит откатить код
./leisure/deploy.sh --check                # убедиться, что всё живо
```

После отката репозиторий стоит на конкретном коммите (detached HEAD); следующий `./leisure/deploy.sh` сам вернёт ветку и
накатит актуальный код — поэтому сначала почини причину провала в репозитории, потом запускай деплой.

## Обслуживание (шпаргалка)

| Что | Команда на сервере (`cd ~/Agents-For-Content/leisure`) |
|---|---|
| Логи | `docker compose logs -f api web caddy` |
| Перезапустить | `docker compose restart api web` |
| Обновить вручную | `cd .. && ./leisure/deploy.sh` |
| Проверить живость | `cd .. && ./leisure/deploy.sh --check` |
| Бэкап сейчас | `cd .. && ./leisure/backup.sh` |
| Откат | `cd .. && ./leisure/rollback.sh latest` |
| Поменять секреты | `nano .env`, затем `docker compose up -d` |
| Перезалить seed | `docker compose exec -T api python -m leisure.seed.load` |
| Место на диске | `docker system df`, старые образы: `docker image prune -f` |

Мониторинг доступности: бесплатный UptimeRobot — HTTPS-проверка `https://ваш-домен/api/health` каждые 5 минут с алертом на почту.
