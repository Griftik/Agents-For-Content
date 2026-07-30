#!/usr/bin/env bash
# ─── Фабрика контента @neurostrategy — подъём сервера (Шаг 0) ───
# Идемпотентный бутстрап чистого VPS (Ubuntu 22.04 / 24.04).
# Запускать на СЕРВЕРЕ под root или через sudo:  sudo bash deploy/bootstrap.sh
# Ничего не удаляет; можно запускать повторно.
set -euo pipefail

APP_USER="${APP_USER:-fabrika}"
APP_DIR="${APP_DIR:-/opt/agents-for-content}"

echo "==> Обновляю списки пакетов и ставлю зависимости"
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install -y python3 python3-venv python3-pip git ffmpeg ufw rclone curl

echo "==> Создаю системного пользователя ${APP_USER} (если ещё нет)"
if ! id "${APP_USER}" &>/dev/null; then
  useradd --system --create-home --shell /bin/bash "${APP_USER}"
fi

echo "==> Готовлю каталог приложения ${APP_DIR}"
mkdir -p "${APP_DIR}"
chown -R "${APP_USER}:${APP_USER}" "${APP_DIR}"

echo "==> Настраиваю фаервол (разрешаю только SSH)"
ufw allow OpenSSH || true
ufw --force enable || true

cat <<EOF

==> Готово. Дальше вручную:
   1) Переключись на пользователя приложения:
        sudo -iu ${APP_USER}
   2) Склонируй репозиторий и создай виртуальное окружение:
        git clone <repo-url> ${APP_DIR} && cd ${APP_DIR}
        python3 -m venv .venv && . .venv/bin/activate
        pip install -r requirements.txt
   3) Создай .env по образцу и впиши секреты:
        cp .env.example .env && nano .env
   4) (Шаг 1) Установи службу бота — см. deploy/contentmaker.service
EOF
