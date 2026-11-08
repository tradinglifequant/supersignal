from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.schemas import LoginRequest, LoginResponse
from app.security.auth import verify_password, create_access_token, get_admin_credentials
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["auth"])

@router.post("/login", response_model=LoginResponse)
async def login(payload: LoginRequest):
    username_cfg, pwd_hash = get_admin_credentials()
    if payload.username != username_cfg or not verify_password(payload.password, pwd_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    token = create_access_token({"sub": payload.username})
    return LoginResponse(access_token=token)
