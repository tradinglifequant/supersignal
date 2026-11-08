from collections import deque
import time

from fastapi import APIRouter, Depends, HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from app.core.config import get_settings
from app.schemas import LoginRequest, LoginResponse
from app.security.auth import (
    TOKEN_HEADER_NAME,
    AuthFailure,
    create_access_token,
    extract_token,
    get_admin_credentials,
    get_current_user,
    revoke_token_payload,
    verify_password,
    verify_token,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# A bounded, process-wide first line of defense for the single-worker prototype.
# A shared reverse-proxy/distributed limiter is still required for deployment.
# Only FAILED attempts are counted, and a success clears the window: counting
# successes too locked the single operator out for a minute after a few re-logins.
_login_attempts: deque[float] = deque()
_LOGIN_LIMIT = 10
_LOGIN_WINDOW_SECONDS = 60


def _prune_login_attempts(now: float) -> None:
    while _login_attempts and _login_attempts[0] <= now - _LOGIN_WINDOW_SECONDS:
        _login_attempts.popleft()


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    username_cfg, pwd_hash = get_admin_credentials()
    now = time.monotonic()
    _prune_login_attempts(now)
    if len(_login_attempts) >= _LOGIN_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")
    password_ok = await run_in_threadpool(verify_password, payload.password, pwd_hash)
    if payload.username != username_cfg or not password_ok:
        _login_attempts.append(now)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    _login_attempts.clear()
    token = create_access_token({"sub": payload.username})
    return LoginResponse(access_token=token)


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    revoke_token_payload(user)
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "exp": user.get("exp")}


@router.get("/diagnose")
async def diagnose(request: Request):
    """Dev-only: report whether a token arrived and why it was rejected.

    Reveals no secret — only header presence and a failure reason. This is what
    makes a preview proxy that drops `Authorization` distinguishable from a bad
    password or an expired session.
    """
    if get_settings().is_production:
        raise HTTPException(status_code=404, detail="Not found")
    authorization = request.headers.get("authorization") or ""
    custom = request.headers.get(TOKEN_HEADER_NAME) or ""
    result: dict = {
        "origin": request.headers.get("origin"),
        "origin_allowed": request.headers.get("origin") in get_settings().cors_origin_list,
        "authorization_header_present": bool(authorization),
        "authorization_scheme_ok": authorization.lower().startswith("bearer "),
        "x_access_token_present": bool(custom),
        "token_verifies": False,
        "failure_reason": None,
    }
    token, source = extract_token(None, request)
    result["token_source"] = source
    if token:
        try:
            payload = verify_token(token)
            result["token_verifies"] = True
            result["username"] = payload.get("sub")
        except AuthFailure as exc:
            result["failure_reason"] = exc.reason
        except HTTPException:
            result["failure_reason"] = "auth_not_configured"
    else:
        result["failure_reason"] = "no_token_header_received"
    return result
