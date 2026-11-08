"""Authentication is mandatory, including in development and on WebSockets."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient
from jose import jwt
from starlette.websockets import WebSocketDisconnect

from app.api.routes.auth import _login_attempts
from app.core.config import get_settings
from app.main import app
from app.security.auth import hash_password


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("ALLOW_DEV_BYPASS", "true")  # legacy flag must not bypass auth
    monkeypatch.setenv("ADMIN_USERNAME", "operator")
    monkeypatch.setenv("ADMIN_PASSWORD_HASH", hash_password("test-only-password"))
    monkeypatch.setenv("JWT_SECRET_KEY", "test-only-signing-key-not-for-real-deployment")
    get_settings.cache_clear()
    _login_attempts.clear()
    yield
    get_settings.cache_clear()


@pytest.fixture
def client(configured):
    with TestClient(app) as c:
        yield c


@pytest.fixture
def token(client):
    response = client.post("/api/auth/login", json={"username": "operator", "password": "test-only-password"})
    assert response.status_code == 200
    return response.json()["access_token"]


@pytest.mark.parametrize("method,path", [
    ("GET", "/api/config"), ("PUT", "/api/config"),
    ("POST", "/api/config/credentials/test"), ("POST", "/api/config/credentials"),
    ("GET", "/api/engine/status"), ("GET", "/api/engine/readiness"),
    ("POST", "/api/engine/start"), ("POST", "/api/engine/stop"),
    ("POST", "/api/engine/emergency-stop"), ("GET", "/api/market/symbols"),
    ("GET", "/api/market/signals"), ("GET", "/api/market/scanner"),
    ("GET", "/api/metrics"), ("GET", "/api/metrics/equity-curve"),
    ("GET", "/api/metrics/performance"), ("GET", "/api/positions"),
    ("GET", "/api/trades"), ("GET", "/api/trades/1"),
    ("GET", "/api/trades/1/orders"), ("GET", "/api/orders"),
    ("GET", "/api/logs"), ("GET", "/api/agent-logs"),
])
def test_private_routes_reject_anonymous_even_with_legacy_bypass(client, method, path):
    assert client.request(method, path).status_code == 401


def test_login_and_authorized_request(client, token):
    assert client.get("/api/config", headers={"Authorization": f"Bearer {token}"}).status_code == 200
    assert client.get("/api/health").status_code == 200
    assert client.post("/api/auth/login", json={"username": "operator", "password": "wrong"}).status_code == 401


@pytest.mark.parametrize("field,value", [("ADMIN_PASSWORD_HASH", ""), ("ADMIN_PASSWORD_HASH", "invalid"), ("JWT_SECRET_KEY", ""), ("JWT_SECRET_KEY", "change-me-jwt-secret-key-32-chars-min")])
def test_login_fails_closed_on_missing_or_invalid_configuration(client, monkeypatch, field, value):
    monkeypatch.setenv(field, value)
    get_settings.cache_clear()
    resp = client.post("/api/auth/login", json={"username": "operator", "password": "test-only-password"})
    assert resp.status_code == 503


def test_unsigned_missing_exp_or_wrong_subject_tokens_rejected(client):
    key = get_settings().jwt_secret_key
    for payload in [{"sub": "operator"}, {"sub": "someone-else", "exp": datetime.now(timezone.utc) + timedelta(minutes=1)}]:
        token = jwt.encode(payload, key, algorithm="HS256")
        assert client.get("/api/config", headers={"Authorization": f"Bearer {token}"}).status_code == 401


def test_websocket_auth_and_origin(client, token):
    with client.websocket_connect("/api/ws", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "authenticate", "token": token})
        assert ws.receive_json()["type"] == "snapshot"
        ws.send_json({"type": "ping"})
        assert ws.receive_json()["type"] == "pong"
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"origin": "http://evil.example"}):
            pass
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws?token=" + token, headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_json({"type": "ping"})
            ws.receive_json()
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_json({"type": "authenticate", "token": "invalid"})
            ws.receive_json()


def test_login_rate_limited(client):
    for _ in range(10):
        response = client.post("/api/auth/login", json={"username": "operator", "password": "wrong"})
        assert response.status_code == 401
    assert client.post("/api/auth/login", json={"username": "operator", "password": "wrong"}).status_code == 429


def test_expired_token_cannot_authenticate_websocket(client):
    token = jwt.encode({"sub": "operator", "exp": datetime.now(timezone.utc) - timedelta(seconds=1)},
                       get_settings().jwt_secret_key, algorithm="HS256")
    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/api/ws", headers={"origin": "http://localhost:5173"}) as ws:
            ws.send_json({"type": "authenticate", "token": token})
            ws.receive_json()


def test_credential_test_never_returns_account_payload(client, token, monkeypatch):
    from app.exchange.binance_adapter import BinanceAdapter
    async def fake_validate(self):
        return True, "ok", {"private_account_data": "must-not-leak"}
    monkeypatch.setattr(BinanceAdapter, "validate_credentials", fake_validate)
    response = client.post("/api/config/credentials/test",
                           headers={"Authorization": f"Bearer {token}"},
                           json={"api_key": "key", "api_secret": "secret", "testnet": True})
    assert response.status_code == 200
    assert response.json() == {"valid": True, "message": "Credential check succeeded"}


def test_websocket_closes_when_session_expires(client):
    import time
    token = jwt.encode({"sub": "operator", "exp": int(time.time()) + 2},
                       get_settings().jwt_secret_key, algorithm="HS256")
    with client.websocket_connect("/api/ws", headers={"origin": "http://localhost:5173"}) as ws:
        ws.send_json({"type": "authenticate", "token": token})
        assert ws.receive_json()["type"] == "snapshot"
        with pytest.raises(WebSocketDisconnect) as exc:
            ws.receive_json()
        assert exc.value.code == 4001


def test_untrusted_cors_origin_not_allowed(client):
    response = client.options("/api/config", headers={"Origin": "http://evil.example",
                              "Access-Control-Request-Method": "GET"})
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
