"""API планировщика досуга (FastAPI). Админка SQLAdmin монтируется на /admin, если задан ADMIN_PASSWORD.

    uvicorn leisure.api.main:app --reload
"""
from __future__ import annotations

from fastapi import FastAPI

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
