"""Stateless Firebase authentication for the hosted FinCompass edition.

The middleware verifies Firebase ID tokens but does not create a FinCompass user
record. Authentication identity remains with Firebase; research activity and
application state are not persisted by this module.
"""
from __future__ import annotations

import os
from typing import Any, Dict, Optional

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

_PUBLIC_PATHS = {
    "/api/health",
    "/api/cloud/config",
}

# The hosting mode is read live from the environment on every call, never cached
# at import. Cloud Run sets these once at process start; the desktop edition never
# sets them, so all cloud paths stay inert without any import-time coupling (and
# tests can toggle them without leaking module state).


def hosted_mode() -> bool:
    return os.getenv("FINCOMPASS_HOSTED_MODE", "0").strip().lower() in {"1", "true", "yes", "on"}


def auth_mode() -> str:
    default = "required" if hosted_mode() else "off"
    mode = os.getenv("FINCOMPASS_AUTH_MODE", default).strip().lower()
    return mode if mode in {"off", "optional", "required"} else "required"


def cloud_config_payload() -> Dict[str, Any]:
    return {
        "hosted": hosted_mode(),
        "auth_mode": auth_mode(),
        "firebase": {
            "project_id": os.getenv("FIREBASE_PROJECT_ID", "").strip(),
            "api_key": os.getenv("FIREBASE_API_KEY", "").strip(),
            "auth_domain": os.getenv("FIREBASE_AUTH_DOMAIN", "").strip(),
        },
        "privacy": {
            "server_side_research_profile": False,
            "server_side_watchlist": False,
            "server_side_portfolio_history": False,
            "server_side_forecast_history": False,
            "temporary_computation": True,
        },
    }


def _firebase_auth_module():
    try:
        import firebase_admin
        from firebase_admin import auth
    except Exception:
        return None, None
    if not firebase_admin._apps:
        project_id = os.getenv("FIREBASE_PROJECT_ID", "").strip()
        options = {"projectId": project_id} if project_id else None
        firebase_admin.initialize_app(options=options)
    return firebase_admin, auth


def verify_bearer_token(header: Optional[str]) -> Optional[Dict[str, Any]]:
    if not header or not header.lower().startswith("bearer "):
        return None
    token = header.split(" ", 1)[1].strip()
    if not token:
        return None
    _, auth = _firebase_auth_module()
    if auth is None:
        return None
    try:
        return dict(auth.verify_id_token(token, check_revoked=False))
    except Exception:
        return None


class CloudAuthMiddleware(BaseHTTPMiddleware):
    """Verify Firebase tokens for hosted API calls without storing user activity."""

    async def dispatch(self, request: Request, call_next):
        request.state.auth_user = None
        if not hosted_mode() or auth_mode() == "off":
            return await call_next(request)

        path = request.url.path
        if not path.startswith("/api/") or path in _PUBLIC_PATHS:
            return await call_next(request)

        claims = verify_bearer_token(request.headers.get("Authorization"))
        request.state.auth_user = claims

        if auth_mode() == "required" and not claims:
            return Response(
                content='{"detail":"Sign in to use FinCompass."}',
                status_code=401,
                media_type="application/json",
                headers={"Cache-Control": "no-store"},
            )
        return await call_next(request)
