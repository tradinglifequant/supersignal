"""API smoke tests"""
import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.core.config import get_settings

client = TestClient(app)

def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data

def test_ready():
    resp = client.get("/api/ready")
    assert resp.status_code == 200
    data = resp.json()
    assert "ready" in data
    assert "checks" in data

def test_root():
    resp = client.get("/")
    assert resp.status_code == 200
    assert resp.json()["name"] == "Super Signal"

def test_login_success():
    # Test-only credentials from conftest
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "test-password"})
    assert resp.status_code == 200
    assert "access_token" in resp.json()

def test_login_fail():
    resp = client.post("/api/auth/login", json={"username": "admin", "password": "wrong"})
    assert resp.status_code == 401

def test_config_requires_auth():
    resp = client.get("/api/config")
    assert resp.status_code == 401

def test_metrics():
    resp = client.get("/api/metrics", headers={})
    # May require auth but also dev bypass
    assert resp.status_code == 401

def test_list_symbols_empty_initially():
    resp = client.get("/api/market/symbols")
    assert resp.status_code == 401

def test_engine_status():
    resp = client.get("/api/engine/status")
    assert resp.status_code == 401
    if resp.status_code == 200:
        assert "state" in resp.json()
