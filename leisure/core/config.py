"""Загрузка scoring.yaml. Один файл — одна функция, с кэшем по пути."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path

import yaml

DEFAULT_PATH = Path(__file__).with_name("scoring.yaml")


@lru_cache(maxsize=8)
def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        data = yaml.safe_load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"scoring config {path}: ожидался словарь")
    return data


def scoring_config(path: str | os.PathLike | None = None) -> dict:
    """Конфиг весов. Порядок: аргумент → переменная SCORING_CONFIG → leisure/core/scoring.yaml."""
    p = Path(path or os.getenv("SCORING_CONFIG") or DEFAULT_PATH)
    return _load(str(p.resolve()))


def reload() -> None:
    _load.cache_clear()
