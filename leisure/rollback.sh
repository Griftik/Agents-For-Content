#!/usr/bin/env bash
# Ручной откат Catch на выбранный бэкап: код на тот sha, что в имени файла (или LAST_GOOD, или --sha), пересборка,
# восстановление базы из дампа.
#   ./leisure/rollback.sh                       # список бэкапов
#   ./leisure/rollback.sh latest                # последний бэкап
#   ./leisure/rollback.sh catch-20261025-040000-006de78.sql.gz [--sha 006de78] [--db-only]
# --db-only: только восстановить базу, код не трогать. Перед откатом снимается ещё один бэкап (catch-...-pre-rollback.sql.gz).
set -euo pipefail
cd "$(dirname "$0")"
BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"

list() { ls -1t "$BACKUP_DIR"/catch-*.sql.gz 2>/dev/null | sed "s#^$BACKUP_DIR/##"; }

if [ $# -eq 0 ]; then
    echo "Бэкапы в $BACKUP_DIR (новые сверху):"
    list || true
    echo; echo "Откат: ./leisure/rollback.sh <файл|latest> [--sha <sha>] [--db-only]"
    exit 0
fi

FILE="$1"; shift
SHA=""; DB_ONLY=0
while [ $# -gt 0 ]; do
    case "$1" in
        --sha) SHA="$2"; shift 2 ;;
        --db-only) DB_ONLY=1; shift ;;
        *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
    esac
done
if [ "$FILE" = "latest" ]; then
    FILE="$(list | head -n1 || true)"
    [ -n "$FILE" ] || { echo "бэкапов нет" >&2; exit 1; }
fi
case "$FILE" in /*) PATH_FILE="$FILE" ;; *) PATH_FILE="$BACKUP_DIR/$FILE" ;; esac
[ -s "$PATH_FILE" ] || { echo "нет файла $PATH_FILE" >&2; exit 1; }
gzip -t "$PATH_FILE" || { echo "дамп битый: $PATH_FILE" >&2; exit 1; }

if [ -z "$SHA" ]; then
    # имя catch-<дата>-<время>-<sha>.sql.gz; метки вроде manual/pre-rollback — берём LAST_GOOD
    SHA="$(basename "$PATH_FILE" .sql.gz | awk -F- '{print $NF}')"
    if ! git cat-file -e "$SHA^{commit}" 2>/dev/null; then
        SHA="$(cat "$BACKUP_DIR/LAST_GOOD" 2>/dev/null || true)"
    fi
fi

restore_db() {
    echo "rollback: останавливаю api и worker, восстанавливаю базу из $PATH_FILE"
    docker compose stop api worker >/dev/null
    docker compose up -d db >/dev/null
    until docker compose exec -T db pg_isready -U leisure -d leisure >/dev/null 2>&1; do sleep 1; done
    # чистим схему целиком: дамп с --clean не знает о таблицах, которых не было в его версии
    docker compose exec -T db psql -U leisure -d leisure -q -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;" >/dev/null
    gunzip -c "$PATH_FILE" | docker compose exec -T db psql -U leisure -d leisure -q -v ON_ERROR_STOP=0 >/dev/null
    echo "rollback: база восстановлена"
}

echo "rollback: страховочный бэкап текущего состояния"
./backup.sh pre-rollback || echo "rollback: страховочный бэкап не снят (база не запущена?) — продолжаю"

if [ "$DB_ONLY" -eq 0 ]; then
    [ -n "$SHA" ] || { echo "не удалось определить sha для отката: укажи --sha" >&2; exit 1; }
    echo "rollback: код → $SHA"
    git -C .. checkout -q "$SHA"
    docker compose build --quiet api worker web
fi
restore_db
docker compose up -d
echo "rollback: готово; код $(git rev-parse --short HEAD), проверка: ./leisure/deploy.sh --check"
