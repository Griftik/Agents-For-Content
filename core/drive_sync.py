"""Синхронизация «рабочей» локальной копии (сервер) с «ценными» данными на Drive.

Архитектурное решение №1 опорного документа: агенты молотят быструю ЛОКАЛЬНУЮ
копию в DATA_DIR, а по расписанию / после важного изменения выгружают ценное на
Google Drive. Принцип: последний записал — прав.

Бэкенд (rclone или Python service-account) финализируется на Шаге 2.
Пока по умолчанию — rclone (готовый инструмент, минимум своего кода).
Используем `copy` (не `sync`), чтобы на этапе фундамента ничего не удалять;
двунаправленность и блокировки добавим на Шаге 2.
"""
from __future__ import annotations

import subprocess

from core.config import DATA_DIR, DRIVE_FOLDER, DRIVE_REMOTE
from core.logging_setup import setup_logging

log = setup_logging("drive_sync", to_file=False)


def _rclone(*args: str) -> None:
    log.info("rclone %s", " ".join(args))
    subprocess.run(["rclone", *args], check=True)


def pull(subpath: str = "") -> None:
    """Скачать «ценное» с Google Drive в локальную рабочую копию."""
    remote = f"{DRIVE_REMOTE}:{DRIVE_FOLDER}/{subpath}".rstrip("/")
    local = DATA_DIR / subpath
    local.mkdir(parents=True, exist_ok=True)
    _rclone("copy", remote, str(local))


def push(subpath: str = "") -> None:
    """Выгрузить «ценное» из локальной копии на Google Drive."""
    remote = f"{DRIVE_REMOTE}:{DRIVE_FOLDER}/{subpath}".rstrip("/")
    local = DATA_DIR / subpath
    _rclone("copy", str(local), remote)


if __name__ == "__main__":
    log.info("drive_sync: интерфейс готов. Бэкенд (rclone) настраивается на Шаге 2.")
