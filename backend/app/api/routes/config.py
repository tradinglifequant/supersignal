from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
import json
import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.models import AppConfig, AuditEvent, ExchangeCredential
from app.db.session import get_db
from app.exchange.binance_adapter import BinanceAdapter
from app.schemas import (
    ConfigResponse,
    ConfigUpdateRequest,
    CredentialsSaveRequest,
    CredentialTestRequest,
)
from app.security.auth import get_current_user
from app.security.encryption import encrypt_value

router = APIRouter(prefix="/config", tags=["config"])


def _has_binance_credentials(settings, db: Session) -> bool:
    if settings.binance_api_key and settings.binance_api_secret:
        return True
    return db.query(ExchangeCredential).filter(ExchangeCredential.exchange == "binance").count() > 0


def _to_config_response(settings, db: Session) -> ConfigResponse:
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
        max_consecutive_losses=settings.max_consecutive_losses,
        max_slippage_bps=str(settings.max_slippage_bps),
        taker_fee_bps=str(settings.taker_fee_bps),
        candidate_ttl_seconds=settings.candidate_ttl_seconds,
        cooldown_seconds=settings.cooldown_seconds,
        protection_deadline_seconds=settings.protection_deadline_seconds,
        binance_testnet=settings.binance_testnet,
        binance_configured=_has_binance_credentials(settings, db),
        threerouter_configured=bool(settings.threerouter_api_key),
    )


def _validate_config_field(field: str, value) -> None:
    if field == "trigger_percentage" and not (Decimal("0.1") <= value <= Decimal("20")):
        raise HTTPException(status_code=400, detail="trigger_percentage must be between 0.1 and 20")
    if field == "trigger_window_seconds" and not (10 <= int(value) <= 3600):
        raise HTTPException(status_code=400, detail="trigger_window_seconds must be between 10 and 3600")
    if field == "base_margin" and not (Decimal("1") <= value <= Decimal("100000")):
        raise HTTPException(status_code=400, detail="base_margin must be >= 1")
    if field == "leverage" and not (1 <= int(value) <= 125):
        raise HTTPException(status_code=400, detail="leverage must be between 1 and 125")
    if field == "max_concurrent_trades" and not (1 <= int(value) <= 50):
        raise HTTPException(status_code=400, detail="max_concurrent_trades must be between 1 and 50")
    if field == "profit_reinvestment_pct" and not (Decimal("0") <= value <= Decimal("100")):
        raise HTTPException(status_code=400, detail="profit_reinvestment_pct must be between 0 and 100")
    if field == "max_trade_allocation" and value <= Decimal("0"):
        raise HTTPException(status_code=400, detail="max_trade_allocation must be > 0")
    if field == "daily_loss_limit" and value <= Decimal("0"):
        raise HTTPException(status_code=400, detail="daily_loss_limit must be > 0")
    if field == "max_drawdown_pct" and not (Decimal("0.1") <= value <= Decimal("100")):
        raise HTTPException(status_code=400, detail="max_drawdown_pct must be between 0.1 and 100")
    if field == "max_aggregate_exposure" and value <= Decimal("0"):
        raise HTTPException(status_code=400, detail="max_aggregate_exposure must be > 0")
    if field == "max_consecutive_losses" and not (1 <= int(value) <= 100):
        raise HTTPException(status_code=400, detail="max_consecutive_losses must be between 1 and 100")
    if field == "max_slippage_bps" and not (Decimal("1") <= value <= Decimal("1000")):
        raise HTTPException(status_code=400, detail="max_slippage_bps must be between 1 and 1000")
    if field == "taker_fee_bps" and not (Decimal("0") <= value <= Decimal("500")):
        raise HTTPException(status_code=400, detail="taker_fee_bps must be between 0 and 500")
    if field == "candidate_ttl_seconds" and not (5 <= int(value) <= 600):
        raise HTTPException(status_code=400, detail="candidate_ttl_seconds must be between 5 and 600")
    if field == "cooldown_seconds" and not (0 <= int(value) <= 86400):
        raise HTTPException(status_code=400, detail="cooldown_seconds must be between 0 and 86400")
    if field == "protection_deadline_seconds" and not (1 <= int(value) <= 120):
        raise HTTPException(status_code=400, detail="protection_deadline_seconds must be between 1 and 120")


@router.get("", response_model=ConfigResponse)
async def get_config(user=Depends(get_current_user), db: Session = Depends(get_db)):
    settings = get_settings()
    cfg = db.query(AppConfig).first()
    if cfg:
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
            max_consecutive_losses=cfg.max_consecutive_losses,
            max_slippage_bps=str(cfg.max_slippage_bps),
            taker_fee_bps=str(cfg.taker_fee_bps),
            candidate_ttl_seconds=cfg.candidate_ttl_seconds,
            cooldown_seconds=cfg.cooldown_seconds,
            protection_deadline_seconds=cfg.protection_deadline_seconds,
            binance_testnet=settings.binance_testnet,
            binance_configured=_has_binance_credentials(settings, db),
            threerouter_configured=bool(settings.threerouter_api_key),
        )
    return _to_config_response(settings, db)


@router.put("", response_model=ConfigResponse)
async def update_config(payload: ConfigUpdateRequest, user=Depends(get_current_user), db: Session = Depends(get_db)):
    cfg = db.query(AppConfig).first()
    settings = get_settings()
    if not cfg:
        cfg = AppConfig(
            id=str(uuid.uuid4()),
            environment=settings.app_env,
            trigger_percentage=settings.trigger_percentage,
            trigger_window_seconds=settings.trigger_window_seconds,
            base_margin=settings.base_margin,
            leverage=settings.leverage,
            max_concurrent_trades=settings.max_concurrent_trades,
            profit_reinvestment_pct=settings.profit_reinvestment_pct,
            max_trade_allocation=settings.max_trade_allocation,
            daily_loss_limit=settings.daily_loss_limit,
            max_drawdown_pct=settings.max_drawdown_pct,
            max_aggregate_exposure=settings.max_aggregate_exposure,
            max_consecutive_losses=settings.max_consecutive_losses,
            max_slippage_bps=settings.max_slippage_bps,
            taker_fee_bps=settings.taker_fee_bps,
            candidate_ttl_seconds=settings.candidate_ttl_seconds,
            cooldown_seconds=settings.cooldown_seconds,
            protection_deadline_seconds=settings.protection_deadline_seconds,
        )
        db.add(cfg)
        db.flush()

    before = {c.name: str(getattr(cfg, c.name)) for c in cfg.__table__.columns}

    for field, value in payload.model_dump(exclude_unset=True).items():
        if value is None:
            continue
        _validate_config_field(field, value)
        setattr(cfg, field, value)

    if cfg.base_margin > cfg.max_trade_allocation:
        raise HTTPException(status_code=400, detail="base_margin cannot exceed max_trade_allocation")

    cfg.updated_at = datetime.now(timezone.utc)
    db.commit()

    after = {c.name: str(getattr(cfg, c.name)) for c in cfg.__table__.columns}
    db.add(
        AuditEvent(
            id=str(uuid.uuid4()),
            actor=user["username"],
            action="config.update",
            before_json=json.dumps(before),
            after_json=json.dumps(after),
        )
    )
    db.commit()

    return await get_config(user, db)


@router.post("/credentials/test")
async def test_credentials(payload: CredentialTestRequest, user=Depends(get_current_user)):
    adapter = BinanceAdapter(api_key=payload.api_key, api_secret=payload.api_secret, testnet=payload.testnet)
    try:
        valid, _msg, _info = await adapter.validate_credentials()
        return {"valid": valid, "message": "Credential check succeeded" if valid else "Credential check failed"}
    finally:
        await adapter.close()


@router.post("/credentials")
async def save_credentials(
    payload: CredentialsSaveRequest,
    user=Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not payload.api_key.strip() or not payload.api_secret.strip():
        raise HTTPException(status_code=400, detail="API key and secret are required")
    settings = get_settings()
    enc_key = encrypt_value(payload.api_key.strip())
    enc_secret = encrypt_value(payload.api_secret.strip())
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
    db.add(
        AuditEvent(
            id=str(uuid.uuid4()),
            actor=user["username"],
            action="credentials.save",
            after_json=json.dumps({"exchange": payload.exchange, "environment": payload.environment}),
        )
    )
    db.commit()
    return {"status": "saved", "id": rec.id}
