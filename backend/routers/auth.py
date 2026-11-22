"""Auth: login/logout/me over an HttpOnly session cookie."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

from backend.deps import COOKIE_NAME, SESSION_MAX_AGE, create_session, destroy_session, is_authed
from backend.deps import verify_password

router = APIRouter()


class LoginBody(BaseModel):
    password: str = ""


@router.get("/me")
def me(ok: Annotated[bool, Depends(is_authed)]):
    return {"authed": ok}


@router.post("/login", status_code=204)
def login(body: LoginBody, request: Request, response: Response):
    if not verify_password(body.password):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "wrong password")
    token = create_session()
    response.set_cookie(
        COOKIE_NAME, token, httponly=True, secure=request.url.scheme == "https",
        samesite="lax", max_age=SESSION_MAX_AGE
    )
    response.headers["Cache-Control"] = "no-store"
    return None


@router.post("/logout", status_code=204)
def logout(
    response: Response,
    session: Annotated[str | None, Cookie(alias=COOKIE_NAME)] = None,
):
    destroy_session(session)
    response.delete_cookie(COOKIE_NAME)
    return None
