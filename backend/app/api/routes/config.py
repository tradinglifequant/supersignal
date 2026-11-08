from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from decimal import Decimal

from app.core.config import get_settings
from app.db.session import get_db
from app.db.models import AppConfig, AuditEvent
from app.schemas import ConfigResponse, ConfigUpdateRequest, CredentialTestRequest, CredentialsSaveRequest
from app.security.auth import get_current_user, get_current_user_optional
from app.security.encryption import encrypt_value
from app.exchange.binance_adapter import BinanceAdapter
import uuid
from datetime import datetime, timezone
import json

router = APIRouter(prefix="/config", tags=["config"])

def _to_config_response(settings) -> ConfigResponse:
    return ConfigResponse(
        environment=settings.app_env,
        trigger_percentage=str(settings.trigger_percentage),
        trigger_window_seconds=settings.trigger_window_seconds,
        base_margin=str(settings.base_margin),
        leverage=settings.leverage,
        max_concurrent_trades=settings.max_concurrent_trades,
        profit_reinvestment_pct=str(settings.profit_reinvestment_pct),
        max_trade_allocation=str(settings.max_trade_allocation),
        daily_loss_limit=str(settings.daily_loss_limit),
        max_drawdown_pct=str(settings.max_drawdown_pct),
        max_aggregate_exposure=str(settings.max_aggregate_exposure),
        max_slippage_bps=str(settings.max_slippage_bps),
        taker_fee_bps=str(settings.taker_fee_bps),
        candidate_ttl_seconds=settings.candidate_ttl_seconds,
        cooldown_seconds=settings.cooldown_seconds,
        protection_deadline_seconds=settings.protection_deadline_seconds,
        binance_testnet=settings.binance_testnet,
        binance_configured=bool(settings.binance_api_key),
        threerouter_configured=bool(settings.threerouter_api_key),
    )

@router.get("", response_model=ConfigResponse)
async def get_config(user=Depends(get_current_user_optional), db: Session = Depends(get_db)):
    settings = get_settings()
    # Try DB override
    cfg = db.query(AppConfig).first()
    if cfg:
        # Map DB to response (use DB values)
        return ConfigResponse(
            environment=cfg.environment,
            trigger_percentage=str(cfg.trigger_percentage),
            trigger_window_seconds=cfg.trigger_window_seconds,
            base_margin=str(cfg.base_margin),
            leverage=cfg.leverage,
            max_concurrent_trades=cfg.max_concurrent_trades,
            profit_reinvestment_pct=str(cfg.profit_reinvestment_pct),
            max_trade_allocation=str(cfg.max_trade_allocation),
            daily_loss_limit=str(cfg.daily_loss_limit),
            max_drawdown_pct=str(cfg.max_drawdown_pct),
            max_aggregate_exposure=str(cfg.max_aggregate_exposure),
            max_slippage_bps=str(cfg.max_slippage_bps),
            taker_fee_bps=str(cfg.taker_fee_bps),
            candidate_ttl_seconds=cfg.candidate_ttl_seconds,
            cooldown_seconds=cfg.cooldown_seconds,
            protection_deadline_seconds=cfg.protection_deadline_seconds,
            binance_testnet=get_settings().binance_testnet,
            binance_configured=bool(get_settings().binance_api_key),
            threerouter_configured=bool(get_settings().threerouter_api_key),
        )
    return _to_config_response(settings)

@router.put("", response_model=ConfigResponse)
async def update_config(payload: ConfigUpdateRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(AppConfig).first()
    settings = get_settings()
    if not cfg:
        cfg = AppConfig(id=str(uuid.uuid4()), environment=settings.app_env)
        db.add(cfg)
    before = {c.name: str(getattr(cfg, c.name)) for c in cfg.__table__.columns}

    # Apply updates with validation
    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        # Validation ranges
        if field == "trigger_percentage" and not (Decimal("0.1") <= value <= Decimal("20")):
            raise HTTPException(status_code=400, detail="trigger_percentage must be 0.1-20")
        if field == "leverage" and not (1 <= int(value) <= 125):
            raise HTTPException(status_code=400, detail="leverage 1-125")
        setattr(cfg, field, value)

    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()

    # audit
    after = {c.name: str(getattr(cfg, c.name)) for c in cfg.__table__.columns}
    db.add(AuditEvent(id=str(uuid.uuid4()), actor=user["username"], action="config.update", before_json=json.dumps(before), after_json=json.dumps(after)))
    db.commit()

    return await get_config(user, db)

@router.post("/credentials/test")
async def test_credentials(payload: CredentialTestRequest):
    adapter = BinanceAdapter(api_key=payload.api_key, api_secret=payload.api_secret, testnet=payload.testnet)
    try:
        valid, msg, info = await adapter.validate_credentials()
        return {"valid": valid, "message": msg, "account_info": info}
    finally:
        await adapter.close()

@router.post("/credentials")
async def save_credentials(payload: CredentialsSaveRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    from app.db.models import ExchangeCredential
    from app.core.config import get_settings
    settings = get_settings()
    # Encrypt
    enc_key = encrypt_value(payload.api_key)
    enc_secret = encrypt_value(payload.api_secret)
    rec = ExchangeCredential(
        id=str(uuid.uuid4()),
        exchange=payload.exchange,
        environment=payload.environment,
        api_key_ciphertext=enc_key,
        api_secret_ciphertext=enc_secret,
        encryption_key_version=settings.encryption_key_version,
    )
    db.add(rec)
    db.commit()
    # audit
    db.add(AuditEvent(id=str(uuid.uuid4()), actor=user["username"], action="credentials.save", after_json=json.dumps({"exchange": payload.exchange, "environment": payload.environment})))
    db.commit()
    return {"status": "saved", "id": rec.id}
