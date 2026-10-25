#!/usr/bin/env bash
# Бэкап базы Catch: pg_dump из контейнера db → ~/backups/catch-<дата>-<sha>.sql.gz (сжатый, с DROP ... IF EXISTS для восстановления).
#   ./leisure/backup.sh            # вручную
#   ./leisure/backup.sh <метка>    # метка вместо sha (deploy.sh передаёт sha работающей версии)
# Cron, ежедневно в 04:00 (ставит server-setup.sh; проверить: crontab -l):
#   0 4 * * * cd $HOME/Agents-For-Content && ./leisure/backup.sh >> $HOME/backups/backup.log 2>&1
# Хранится 30 последних копий (BACKUP_KEEP). Скачать копию себе: scp USER@IP:~/backups/catch-ДАТА-SHA.sql.gz ~/catch-backups/
set -euo pipefail
cd "$(dirname "$0")"

BACKUP_DIR="${BACKUP_DIR:-$HOME/backups}"
KEEP="${BACKUP_KEEP:-30}"
LABEL="${1:-$(git rev-parse --short HEAD 2>/dev/null || echo manual)}"
mkdir -p "$BACKUP_DIR"

if ! docker compose ps --status running --services 2>/dev/null | grep -qx db; then
    echo "backup: контейнер db не запущен — бэкап невозможен" >&2
    exit 2
fi

STAMP="$(date +%Y%m%d-%H%M%S)"
OUT="$BACKUP_DIR/catch-${STAMP}-${LABEL}.sql.gz"
TMP="$OUT.part"
# --clean --if-exists: дамп сам снесёт таблицы перед восстановлением; pg_dump идёт внутри контейнера, наружу — уже gzip
docker compose exec -T db pg_dump -U leisure -d leisure --clean --if-exists --no-owner --no-privileges | gzip -6 > "$TMP"
if [ ! -s "$TMP" ] || ! gzip -t "$TMP"; then
    rm -f "$TMP"
    echo "backup: дамп пустой или битый" >&2
    exit 1
fi
mv "$TMP" "$OUT"
echo "backup: $OUT ($(du -h "$OUT" | cut -f1))"

# ротация: оставить KEEP последних
ls -1t "$BACKUP_DIR"/catch-*.sql.gz 2>/dev/null | tail -n +"$((KEEP + 1))" | xargs -r rm -f
echo "backup: копий в $BACKUP_DIR: $(ls -1 "$BACKUP_DIR"/catch-*.sql.gz 2>/dev/null | wc -l) (храним $KEEP)"
