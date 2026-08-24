"""Shared API dependencies: the database connection and the bearer token gate.

docs/03_SECURITY_AND_ACCESS.md section 9:

  The API binds to 127.0.0.1:8000; the Vite dev server binds to 127.0.0.1:5173 and proxies /api.
  Read routes are open on loopback. Mutating routes require Authorization: Bearer
  <SALVAGE_DASHBOARD_TOKEN>. CORS allows only the Vite origin. There is no user model, no
  sessions, no roles.

The connection is a per-thread one, for the reason recorded in docs/BUILD_LOG.md under M2
carry-over 4: a connection shared across threads interleaves transactions.
"""

from __future__ import annotations

import hmac
from collections.abc import Callable
from typing import Annotated, Any

from fastapi import Depends, Header, HTTPException

from salvage.config import Settings, get_settings
from salvage.db import thread_connection


def get_connection_factory() -> Callable[[], Any]:
    """A factory, not a connection. See salvage/ingest/webhooks.py for why."""
    return thread_connection


ConnFactory = Annotated[Callable[[], Any], Depends(get_connection_factory)]


def require_token(authorization: Annotated[str | None, Header()] = None) -> None:
    """Refuse anything that is not the configured bearer token.

    Constant-time comparison, the same as the webhook signature check. The token is short and the
    endpoint is on loopback, so a timing attack is not the realistic threat, but there is no
    reason to write the version that leaks.

    An unset token refuses everything rather than allowing everything. A deployment that forgot to
    configure a token is not a deployment where every mutating route should be open.
    """
    settings: Settings = get_settings()
    expected = settings.salvage_dashboard_token
    if not expected:
        raise HTTPException(
            status_code=503,
            detail="SALVAGE_DASHBOARD_TOKEN is not set, so no mutating route is available",
        )
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="missing bearer token")
    supplied = authorization.removeprefix("Bearer ").strip()
    if not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=403, detail="invalid token")


TokenGate = Depends(require_token)
