"""Точка входа симулятора: `python -m leisure.sim.runner --users 50 --weeks 4 --seed 20261024`. Версия 2 — приложение без Telegram (sim/app)."""
from __future__ import annotations

import sys

from .app.sim import main, run_app_simulation  # noqa: F401

if __name__ == "__main__":
    sys.exit(main())
