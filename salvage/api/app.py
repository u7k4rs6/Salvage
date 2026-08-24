"""FastAPI application.

Route surface is docs/04_FRONTEND_SPEC.md section 5. Binding, CORS and the token rule are
docs/03_SECURITY_AND_ACCESS.md section 9:

  The API binds to 127.0.0.1:8000; the Vite dev server binds to 127.0.0.1:5173 and proxies /api.
  Read routes are open on loopback. Mutating routes require Authorization: Bearer
  <SALVAGE_DASHBOARD_TOKEN>. CORS allows only the Vite origin.

Read routes are open because the bind address is the access control: nothing off this machine can
reach them. Mutating routes are gated anyway, because a page in any other tab of the same browser
is also on this machine, and a link that quietly closes an incident is a real thing.
"""

from __future__ import annotations

from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from salvage import __version__
from salvage.api import (
    routes_escalations,
    routes_incidents,
    routes_ledger,
    routes_results,
    routes_sim,
)
from salvage.api.stream import event_source
from salvage.config import get_settings
from salvage.ingest import webhooks

# The Vite dev server and the built dashboard when served by `vite preview`. Both loopback, both
# fixed ports. Anything else is refused rather than reflected.
ALLOWED_ORIGINS = [
    "http://127.0.0.1:5173",
    "http://localhost:5173",
    "http://127.0.0.1:4173",
    "http://localhost:4173",
]


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Salvage", version=__version__, docs_url=None, redoc_url=None)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Authorization", "Content-Type"],
    )

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {
            "status": "ok",
            "version": __version__,
            "env": settings.salvage_env,
            "kill_switch": get_settings().salvage_kill_switch,
            "llm_provider": settings.salvage_llm_provider,
            "token_configured": bool(settings.salvage_dashboard_token),
        }

    @app.get("/api/stream")
    async def stream() -> EventSourceResponse:
        """One SSE connection per open tab. Names are fixed in salvage/api/stream.py."""
        return EventSourceResponse(event_source())

    # The unsigned replay route is registered only in dev. Outside dev it does not exist on the
    # router at all (security doc section 4). The router is built per application rather than
    # shared, so one process cannot create a dev app and then leak that route into a demo app.
    app.include_router(webhooks.build_router(include_dev_replay=settings.is_dev))
    app.include_router(routes_incidents.router)
    app.include_router(routes_escalations.router)
    app.include_router(routes_ledger.router)
    app.include_router(routes_results.router)
    app.include_router(routes_sim.router)
    return app


app = create_app()
