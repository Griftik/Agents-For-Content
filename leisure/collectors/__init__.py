"""Коллекторы источников (п. 7.1 спеки). Интерфейс и реестр — в base.py, по модулю на источник."""
from __future__ import annotations

import importlib
import pkgutil

NOT_SOURCES = frozenset({"base", "pipeline"})  # служебные модули пакета; общий код источников лежит в _common.py


def load_collectors() -> list[str]:
    """Импортирует все модули-источники пакета, чтобы сработали декораторы @register. Возвращает имена модулей.

    Источники друг про друга не знают: воркер вызывает эту функцию, а затем base.collect_all().
    """
    loaded = []
    for mod in pkgutil.iter_modules(__path__):
        if mod.name not in NOT_SOURCES and not mod.name.startswith("_"):
            importlib.import_module(f"{__name__}.{mod.name}")
            loaded.append(mod.name)
    return sorted(loaded)
