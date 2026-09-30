#!/usr/bin/env bash
# Установка и обновление бота «Заявка на разбор» на чистом Ubuntu 22.04/24.04 одной командой:
#
#   curl -fsSL https://raw.githubusercontent.com/Griftik/Agents-For-Content/claude/mvp-section-16-2rcya3/zayavka_bot/deploy/install.sh | sudo bash
#
# Первый запуск: ставит Docker, скачивает код, спрашивает токен бота (ввод скрыт), запускает.
# Повторный запуск той же командой = обновление: код и content/ обновляются,
# .env, база (storage/) и secrets/ остаются как были.
set -euo pipefail

REPO="Griftik/Agents-For-Content"
BRANCH="${BRANCH:-claude/mvp-section-16-2rcya3}"
DIR="/opt/zayavka_bot"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }

[ "$(id -u)" = 0 ] || { echo "Запустите через sudo"; exit 1; }

if ! command -v docker >/dev/null 2>&1; then
  say "1/4 Ставлю Docker…"
  curl -fsSL https://get.docker.com | sh
else
  say "1/4 Docker уже есть"
fi

say "2/4 Скачиваю код (ветка $BRANCH)…"
TMP="$(mktemp -d)"
curl -fsSL "https://codeload.github.com/$REPO/tar.gz/refs/heads/$BRANCH" | tar -xz -C "$TMP"
SRC="$(find "$TMP" -maxdepth 2 -type d -name zayavka_bot | head -1)"
mkdir -p "$DIR"
# обновляем всё, кроме рабочих данных и секретов
tar -C "$SRC" --exclude=./.env --exclude=./storage --exclude=./secrets -cf - . | tar -C "$DIR" -xf -
mkdir -p "$DIR/storage" "$DIR/secrets"
chown -R 1000:1000 "$DIR/storage"
rm -rf "$TMP"

say "3/4 Настройки"
cd "$DIR"
if [ ! -f .env ]; then
  cp .env.example .env
fi
if ! grep -qE '^BOT_TOKEN=.+' .env; then
  printf 'Вставьте токен бота от @BotFather (символы не видны) и нажмите Enter: '
  read -rs TOKEN </dev/tty; echo
  [ -n "$TOKEN" ] || { echo "Токен пустой — запустите команду ещё раз"; exit 1; }
  sed -i "s|^BOT_TOKEN=.*|BOT_TOKEN=$TOKEN|" .env
fi
chmod 600 .env

say "4/4 Запускаю…"
docker compose up -d --build
sleep 8
if docker compose logs --tail=50 bot | grep -q "запущен"; then
  say "Готово: бот работает. Напишите ему /start."
else
  docker compose logs --tail=30 bot
  say "Бот не запустился — пришлите Claude текст выше."
  exit 1
fi
