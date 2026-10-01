#!/usr/bin/env bash
# Установка и обновление бота «Заявка на разбор» на чистом Ubuntu 22.04/24.04 одной командой:
#
#   curl -fsSL https://raw.githubusercontent.com/Griftik/Agents-For-Content/claude/mvp-section-16-2rcya3/zayavka_bot/deploy/install.sh | sudo bash
#
# Первый запуск: ставит Docker, скачивает код, спрашивает токен бота (ввод скрыт), настраивает
# https-адрес мини-приложения (IP.sslip.io, домен не нужен), запускает бот и приложение.
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
# адрес мини-приложения: свой домен (WEBAPP_HOST=… перед командой) или IP.sslip.io
grep -q '^WEBAPP_HOST=' .env || echo 'WEBAPP_HOST=' >> .env
grep -q '^WEBAPP_URL=' .env || echo 'WEBAPP_URL=' >> .env
if ! grep -qE '^WEBAPP_HOST=.+' .env; then
  HOST="${WEBAPP_HOST:-}"
  if [ -z "$HOST" ]; then
    IP="$(curl -4 -fsS https://api.ipify.org || curl -4 -fsS https://ifconfig.me)"
    HOST="${IP//./-}.sslip.io"
  fi
  sed -i "s|^WEBAPP_HOST=.*|WEBAPP_HOST=$HOST|; s|^WEBAPP_URL=.*|WEBAPP_URL=https://$HOST|" .env
fi
WEBAPP_URL="$(grep -E '^WEBAPP_URL=' .env | cut -d= -f2-)"
chmod 600 .env

say "4/4 Запускаю…"
docker compose up -d --build
sleep 10
if docker compose logs --tail=50 bot | grep -q "запущен"; then
  for i in $(seq 1 30); do   # сертификат выпускается за 10–60 секунд
    curl -fsS -o /dev/null "$WEBAPP_URL/health" && break
    sleep 3
  done
  if curl -fsS -o /dev/null "$WEBAPP_URL/health"; then
    say "Готово: бот и приложение работают."
  else
    say "Бот работает, но https для приложения ещё не готов — проверьте, что открыты порты 80 и 443."
  fi
  cat <<MSG

Адрес мини-приложения: $WEBAPP_URL

Последний шаг — кнопка «Открыть» в профиле бота (как у @invites_tgbot):
  @BotFather → /mybots → бот → Bot Settings → Configure Mini App → Enable Mini App
  → пришлите адрес: $WEBAPP_URL
MSG
else
  docker compose logs --tail=30 bot
  say "Бот не запустился — пришлите Claude текст выше."
  exit 1
fi
