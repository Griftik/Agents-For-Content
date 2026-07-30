"""Единый формат логов для всех агентов Фабрики."""
from __future__ import annotations

import logging

from core.config import DATA_DIR

_FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"


def setup_logging(name: str, *, to_file: bool = True) -> logging.Logger:
    """Возвращает настроенный логгер. Пишет в консоль и (опц.) в data/logs."""
    logging.basicConfig(level=logging.INFO, format=_FORMAT)
    logger = logging.getLogger(name)

    if to_file:
        log_dir = DATA_DIR / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_dir / f"{name}.log", encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        logger.addHandler(handler)

    return logger
