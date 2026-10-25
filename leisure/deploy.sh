#!/usr/bin/env bash
# Обновление Catch на сервере, как в Miru, но с обязательным бэкапом перед накатом и автооткатом:
#   git pull --ff-only → бэкап базы (catch-<дата>-<sha работающей версии>.sql.gz) и LAST_GOOD → docker compose up -d --build
#   → alembic upgrade head → проверка живости api и web → при провале: код на LAST_GOOD, пересборка, восстановление дампа.
#   ./leisure/deploy.sh            # полный цикл (его запускает GitHub Actions после зелёных тестов)
#   ./leisure/deploy.sh --check    # только проверка живости
# Переменные: DEPLOY_BRANCH (по умолчанию текущая ветка), BACKUP_DIR (~/backups), HEALTH_TIMEOUT (120 с), DOMAIN из .env.
set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
HEALTH_TIMEOUT="${HEALTH_TIMEOUT:-120}"
mkdir -p "$BACKUP_DIR"

log() { echo "[deploy $(date +%H:%M:%S)] $*"; }

health() {
    docker compose exec -T api python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=3)" >/dev/null 2>&1 \
    && docker compose exec -T web wget -qO- http://127.0.0.1:3000/api/health >/dev/null 2>&1 \
    && docker compose exec -T web wget -qO- http://127.0.0.1:3000/ >/dev/null 2>&1
}

wait_healthy() {
    local waited=0
    until health; do
        sleep 5; waited=$((waited + 5))
        if [ "$waited" -ge "$HEALTH_TIMEOUT" ]; then return 1; fi
    done
    # через Caddy и домен — предупреждение, не провал (DNS или сертификат могут ещё не подняться)
    local domain; domain="$(grep -E '^DOMAIN=' .env 2>/dev/null | cut -d= -f2- || true)"
    if [ -n "$domain" ] && ! curl -fsS --max-time 10 "https://$domain/api/health" >/dev/null 2>&1; then
        log "ВНИМАНИЕ: https://$domain/api/health не отвечает (DNS, сертификат или firewall), контейнеры при этом живы"
    fi
    return 0
}

if [ "${1:-}" = "--check" ]; then
    if health; then log "ок: api и web живы ($(git rev-parse --short HEAD))"; exit 0; else log "ПРОВАЛ проверки живости"; exit 1; fi
fi

BRANCH="${DEPLOY_BRANCH:-$(git rev-parse --abbrev-ref HEAD)}"
if [ "$BRANCH" = "HEAD" ]; then
    BRANCH="$(cat "$BACKUP_DIR/BRANCH" 2>/dev/null || echo main)"
    log "репозиторий в состоянии отката (detached), возвращаюсь на ветку $BRANCH"
    git -C "$REPO" checkout -q "$BRANCH"
fi
echo "$BRANCH" > "$BACKUP_DIR/BRANCH"
OLD_SHA="$(git rev-parse --short HEAD)"

log "1/5 git pull --ff-only origin $BRANCH"
git -C "$REPO" pull --ff-only origin "$BRANCH"
NEW_SHA="$(git rev-parse --short HEAD)"
log "код: $OLD_SHA → $NEW_SHA"

log "2/5 бэкап базы перед накатом"
if docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    ./backup.sh "$OLD_SHA"
    echo "$OLD_SHA" > "$BACKUP_DIR/LAST_GOOD"
    DUMP="$(ls -1t "$BACKUP_DIR"/catch-*-"$OLD_SHA".sql.gz | head -n1)"
else
    log "база ещё не запущена (первый запуск) — бэкапа нет, откат будет только по коду"
    DUMP=""
fi

log "3/5 docker compose up -d --build"
docker compose up -d --build --remove-orphans

log "4/5 миграции"
until docker compose exec -T db pg_isready -U leisure -d leisure >/dev/null 2>&1; do sleep 1; done
docker compose exec -T api alembic -c leisure/alembic.ini upgrade head

log "5/5 проверка живости (до ${HEALTH_TIMEOUT} с)"
if wait_healthy; then
    echo "$NEW_SHA" > "$BACKUP_DIR/LAST_GOOD"
    docker compose ps
    log "ГОТОВО: $NEW_SHA; бэкапов в $BACKUP_DIR: $(ls -1 "$BACKUP_DIR"/catch-*.sql.gz 2>/dev/null | wc -l)"
    exit 0
fi

log "ПРОВАЛ проверки живости — откат на $OLD_SHA"
docker compose logs --tail=50 api web || true
git -C "$REPO" checkout -q "$OLD_SHA"
docker compose up -d --build --remove-orphans
if [ -n "$DUMP" ]; then
    ./rollback.sh "$DUMP" --db-only
fi
if wait_healthy; then
    log "откат выполнен: работает $OLD_SHA (репозиторий в detached HEAD; следующий ./leisure/deploy.sh вернёт ветку $BRANCH). Разбирайся с $NEW_SHA."
else
    log "откат НЕ помог: сервис не отвечает. Смотри docker compose logs, бэкап: ${DUMP:-нет}"
fi
exit 1
