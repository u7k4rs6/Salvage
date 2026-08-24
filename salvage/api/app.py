"""FastAPI application.

M1 ships two routes only: the webhook receiver and a health check. Dashboard routes land in M2 and
M4 (docs/04_FRONTEND_SPEC.md).

The app binds to 127.0.0.1 (security doc section 9). CORS is not configured because there is no
browser origin to allow until the Vite dashboard exists.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI

from salvage import __version__
from salvage.config import get_settings
from salvage.ingest import webhooks


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Salvage", version=__version__, docs_url=None, redoc_url=None)

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.salvage_env,
            "kill_switch": settings.salvage_kill_switch,
            "llm_provider": settings.salvage_llm_provider,
        }

    # The unsigned replay route is registered only in dev. Outside dev it does not exist on the
    # router at all (security doc section 4). The router is built per application rather than
    # shared, so one process cannot create a dev app and then leak that route into a demo app.
    app.include_router(webhooks.build_router(include_dev_replay=settings.is_dev))
    return app


app = create_app()
