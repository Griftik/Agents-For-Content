"""API планировщика досуга (FastAPI). Админка SQLAdmin монтируется на /admin, если задан ADMIN_PASSWORD.

    uvicorn leisure.api.main:app --reload
"""
from __future__ import annotations

import logging

from fastapi import FastAPI

from leisure import settings
from leisure.admin.views import mount_admin

from .routers import catalog, decisions, digest, events, profiles

app = FastAPI(title="Планировщик досуга по ценностям", version="0.1.0",
              description="Ядро: события, профили, решения, скоринг, дайджест и план. Спека — leisure/docs/SPEC.md.")

for r in (catalog.router, events.router, profiles.router, decisions.router, digest.router):
    app.include_router(r)


@app.get("/health", tags=["служебное"])
def health() -> dict:
    return {"ok": True}


mount_admin(app)
if not settings.API_KEY:
    if settings.DEV_OPEN_API:
        logging.getLogger("leisure.api").warning("LEISURE_DEV_OPEN_API=1: маршруты профиля/решений/дайджеста открыты без ключа")
    else:
        logging.getLogger("leisure.api").error("API_KEY не задан — закрытые маршруты отвечают 503, задай API_KEY в .env")
