"""HTTP-сервер мини-приложения: статика (index.html, app.js, app.css) и /api/*.

Работает в том же процессе, что и бот. Снаружи его закрывает Caddy с https-сертификатом.
"""
from __future__ import annotations

from pathlib import Path

from aiogram import Bot
from aiohttp import web

from bot.webapp.api import BOT_KEY, action_handler, state_handler

STATIC = Path(__file__).parent / "static"


@web.middleware
async def no_cache(request: web.Request, handler):
    resp = await handler(request)
    # Telegram держит webview в кэше — после обновления бота человек должен видеть новую версию
    resp.headers["Cache-Control"] = "no-cache"
    return resp


async def index(_: web.Request) -> web.FileResponse:
    return web.FileResponse(STATIC / "index.html")


async def health(_: web.Request) -> web.Response:
    return web.json_response({"ok": True})


def create_app(bot: Bot) -> web.Application:
    app = web.Application(middlewares=[no_cache], client_max_size=64 * 1024)
    app[BOT_KEY] = bot
    app.router.add_get("/", index)
    app.router.add_get("/health", health)
    app.router.add_post("/api/state", state_handler)
    app.router.add_post("/api/action", action_handler)
    app.router.add_static("/static/", STATIC)
    return app


async def start(bot: Bot, port: int) -> web.AppRunner:
    runner = web.AppRunner(create_app(bot), access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", port).start()  # noqa: S104 — внутри docker-сети, снаружи Caddy
    return runner
