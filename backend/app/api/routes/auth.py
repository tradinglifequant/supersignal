from collections import deque
import time

from fastapi import APIRouter, Depends, HTTPException, status
from starlette.concurrency import run_in_threadpool

from app.schemas import LoginRequest, LoginResponse
from app.security.auth import (
    create_access_token,
    get_admin_credentials,
    get_current_user,
    revoke_token_payload,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])

# A bounded, process-wide first line of defense for the single-worker prototype.
# A shared reverse-proxy/distributed limiter is still required for deployment.
_login_attempts: deque[float] = deque()
_LOGIN_LIMIT = 10
_LOGIN_WINDOW_SECONDS = 60


@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    username_cfg, pwd_hash = get_admin_credentials()
    now = time.monotonic()
    while _login_attempts and _login_attempts[0] <= now - _LOGIN_WINDOW_SECONDS:
        _login_attempts.popleft()
    if len(_login_attempts) >= _LOGIN_LIMIT:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail="Too many login attempts")
    _login_attempts.append(now)
    password_ok = await run_in_threadpool(verify_password, payload.password, pwd_hash)
    if payload.username != username_cfg or not password_ok:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": payload.username})
    return LoginResponse(access_token=token)


@router.post("/logout")
async def logout(user: dict = Depends(get_current_user)):
    revoke_token_payload(user)
    return {"status": "logged_out"}


@router.get("/me")
async def me(user: dict = Depends(get_current_user)):
    return {"username": user["username"], "exp": user.get("exp")}
