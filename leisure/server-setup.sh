#!/usr/bin/env bash
# Первичная настройка Catch на чистом сервере (Ubuntu 22.04/24.04). Запускать из клона репозитория:
#   git clone https://github.com/Griftik/Agents-For-Content.git ~/Agents-For-Content
#   cd ~/Agents-For-Content && ./leisure/server-setup.sh
# Скрипт сам: ставит Docker, спрашивает домен и секреты (собирает leisure/.env), поднимает compose с Caddy (HTTPS сам),
# применяет миграции, загружает seed, ставит ежедневный бэкап в cron и печатает, что вставить в настройки GitHub для автодеплоя.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"

gen() { openssl rand -hex "${1:-32}" 2>/dev/null || head -c "${1:-32}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }
ask() {  # ask VAR "подсказка" [значение по умолчанию] [secret]
    local var="$1" prompt="$2" def="${3:-}" secret="${4:-}" val
    if [ -n "$secret" ]; then read -rsp "$prompt${def:+ [Enter — сгенерировать]}: " val; echo; else read -rp "$prompt${def:+ [$def]}: " val; fi
    printf -v "$var" '%s' "${val:-$def}"
}

echo "=== 1/6 Docker и git ==="
if command -v docker >/dev/null 2>&1 && docker compose version >/dev/null 2>&1; then
    echo "Docker уже установлен."
else
    echo "Ставлю Docker (пара минут)…"
    curl -fsSL https://get.docker.com | sh
fi
command -v git >/dev/null 2>&1 || { apt-get update -qq && apt-get install -y -qq git; }
command -v curl >/dev/null 2>&1 || apt-get install -y -qq curl

echo
echo "=== 2/6 Домен и секреты (leisure/.env) ==="
if [ -f .env ]; then
    echo "leisure/.env уже есть — не трогаю (правка: nano leisure/.env, затем docker compose up -d)."
else
    SERVER_IP="$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
    ask DOMAIN "Домен (A-запись уже на $SERVER_IP; пусто — пока без домена, http://$SERVER_IP)" ""
    if [ -n "$DOMAIN" ]; then WEB_BASE_URL="https://$DOMAIN"; else WEB_BASE_URL="http://$SERVER_IP"; fi
    ask API_KEY "API_KEY (ключ между вебом и API)" "$(gen 32)" secret
    ask SECRET_KEY "SECRET_KEY (сессии админки)" "$(gen 32)" secret
    ask SESSION_SECRET "SESSION_SECRET (cookie сессии веба)" "$(gen 32)" secret
    ask POSTGRES_PASSWORD "Пароль PostgreSQL" "$(gen 16)" secret
    ask ADMIN_USER "Логин админки" "admin"
    ask ADMIN_PASSWORD "Пароль админки" "$(gen 12)" secret
    echo "Почта для входа по ссылке (необязательно; без неё кнопка «почта» в приложении помечена «скоро»):"
    ask SMTP_HOST "SMTP_HOST (например smtp.yandex.ru; пусто — пропустить)" ""
    SMTP_PORT=587; SMTP_USER=""; SMTP_PASSWORD=""; SMTP_FROM=""; SMTP_SSL=0
    if [ -n "$SMTP_HOST" ]; then
        ask SMTP_PORT "SMTP_PORT" "465"
        ask SMTP_USER "SMTP_USER (ящик)" ""
        ask SMTP_PASSWORD "SMTP_PASSWORD (пароль приложения)" "" secret
        ask SMTP_FROM "SMTP_FROM" "$SMTP_USER"
        [ "$SMTP_PORT" = "465" ] && SMTP_SSL=1
    fi
    umask 077
    cat > .env <<ENV
# Catch — секреты сервера (создано server-setup.sh $(date +%F)). В git не попадает. Шаблон и описание — .env.example.
DOMAIN=$DOMAIN
WEB_BASE_URL=$WEB_BASE_URL
POSTGRES_PASSWORD=$POSTGRES_PASSWORD
DATABASE_URL=postgresql+psycopg://leisure:$POSTGRES_PASSWORD@db:5432/leisure
REDIS_URL=redis://redis:6379/0
API_KEY=$API_KEY
SECRET_KEY=$SECRET_KEY
SESSION_SECRET=$SESSION_SECRET
ADMIN_USER=$ADMIN_USER
ADMIN_PASSWORD=$ADMIN_PASSWORD
LEISURE_CITY=Москва
LEISURE_TZ=Europe/Moscow
SMTP_HOST=$SMTP_HOST
SMTP_PORT=$SMTP_PORT
SMTP_USER=$SMTP_USER
SMTP_PASSWORD=$SMTP_PASSWORD
SMTP_FROM=$SMTP_FROM
SMTP_SSL=$SMTP_SSL
ENV
    chmod 600 .env
    echo "leisure/.env создан (права 600). Пароль админки: $ADMIN_PASSWORD — запиши."
fi
mkdir -p "$HOME/backups"

echo
echo "=== 3/6 Сборка и запуск (первая сборка 3–6 минут) ==="
docker compose up -d --build
until docker compose exec -T db pg_isready -U leisure -d leisure >/dev/null 2>&1; do sleep 2; done
docker compose exec -T api alembic -c leisure/alembic.ini upgrade head

echo
echo "=== 4/6 Seed (177 событий прототипа, upsert по slug) ==="
docker compose exec -T api python -m leisure.seed.load
git rev-parse --short HEAD > "$HOME/backups/LAST_GOOD"
git rev-parse --abbrev-ref HEAD > "$HOME/backups/BRANCH"
./backup.sh initial || true

echo
echo "=== 5/6 Ежедневный бэкап (cron 04:00) ==="
CRON_LINE="0 4 * * * cd $REPO && ./leisure/backup.sh >> $HOME/backups/backup.log 2>&1"
if crontab -l 2>/dev/null | grep -Fq "leisure/backup.sh"; then
    echo "строка cron уже есть."
else
    (crontab -l 2>/dev/null || true; echo "$CRON_LINE") | crontab -
    echo "добавлено в crontab: $CRON_LINE"
fi

echo
echo "=== 6/6 Ключ для автодеплоя ==="
if [ ! -f "$HOME/.ssh/deploy_ci" ]; then
    mkdir -p "$HOME/.ssh"
    ssh-keygen -t ed25519 -N "" -f "$HOME/.ssh/deploy_ci" -q
    cat "$HOME/.ssh/deploy_ci.pub" >> "$HOME/.ssh/authorized_keys"
    chmod 700 "$HOME/.ssh"; chmod 600 "$HOME/.ssh/authorized_keys"
fi
SERVER_IP="$(curl -fsS --max-time 5 https://ifconfig.me 2>/dev/null || hostname -I | awk '{print $1}')"
DOMAIN_NOW="$(grep -E '^DOMAIN=' .env | cut -d= -f2- || true)"

docker compose ps
echo
echo "================================================================"
echo "ГОТОВО. Catch запущен: ${DOMAIN_NOW:+https://$DOMAIN_NOW  (}http://$SERVER_IP${DOMAIN_NOW:+)}"
echo "Админка: /admin (логин и пароль из leisure/.env). Проверка: ./leisure/deploy.sh --check"
echo
echo "Автодеплой на GitHub: репозиторий → Settings → Secrets and variables → Actions"
echo "Вкладка Secrets → New repository secret (три штуки):"
echo "  DEPLOY_HOST     = ${SERVER_IP}"
echo "  DEPLOY_USER     = $(whoami)"
echo "  DEPLOY_SSH_KEY  = всё, что напечатано ниже (включая строки BEGIN/END):"
echo "----------------------------------------------------------------"
cat "$HOME/.ssh/deploy_ci"
echo "----------------------------------------------------------------"
echo "Вкладка Variables → New repository variable:"
echo "  DEPLOY_ENABLED  = true"
echo
echo "Бэкапы: $HOME/backups (ежедневно 04:00, 30 копий). Скачать себе: scp $(whoami)@$SERVER_IP:~/backups/catch-*.sql.gz ~/catch-backups/"
echo "Логи: cd $REPO/leisure && docker compose logs -f api web caddy"
echo "================================================================"
