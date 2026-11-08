#!/usr/bin/env bash
set -euo pipefail
echo "Super Signal - Dev environment setup"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example - configure ADMIN_PASSWORD_HASH and JWT_SECRET_KEY before login"
fi

mkdir -p data backend/data

PYTHON_BIN="${PYTHON_BIN:-$(command -v python3 || command -v python)}"

if [ ! -d .venv ]; then
  "$PYTHON_BIN" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
pip install -e .
echo "Backend dependencies installed"

if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm ci)
fi

echo "Setup complete. Next steps:"
echo "  source .venv/bin/activate && (cd backend && alembic upgrade head)"
echo "  PYTHONPATH=backend uvicorn app.main:app --reload --host 127.0.0.1 --port 8000"
echo "  (cd frontend && npm run dev)"
