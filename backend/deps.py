"""Session auth reusing the Streamlit password gate (app/auth.py)."""
from __future__ import annotations

import secrets
from threading import Lock
from time import monotonic
from typing import Annotated

from fastapi import Cookie, Depends, HTTPException, status

from app.auth import SESSION_KEY, check_password  # noqa: F401  (single source of truth)

COOKIE_NAME = "pl_session"
SESSION_MAX_AGE = 30 * 24 * 3600
_sessions: dict[str, float] = {}
_session_lock = Lock()


def create_session() -> str:
    token = secrets.token_urlsafe(32)
    now = monotonic()
    with _session_lock:
        for expired in [key for key, deadline in _sessions.items() if deadline <= now]:
            del _sessions[expired]
        _sessions[token] = now + SESSION_MAX_AGE
    return token


def destroy_session(token: str | None) -> None:
    if token:
        with _session_lock:
            _sessions.pop(token, None)


def is_authed(session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None) -> bool:
    if not session:
        return False
    with _session_lock:
        deadline = _sessions.get(session)
        if deadline is not None and monotonic() < deadline:
            return True
        _sessions.pop(session, None)
        return False


def verify_password(candidate: str | None) -> bool:
    return check_password(candidate)


def require_admin(ok: Annotated[bool, Depends(is_authed)]) -> bool:
    if not ok:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "archivist login required")
    return True
