#!/usr/bin/env bash
set -e
echo "Super Signal - Windows/Posix dev setup"

if [ ! -f .env ]; then
  cp .env.example .env
  echo "Created .env from .env.example - edit your keys"
fi

mkdir -p data

# Backend venv
if [ ! -d backend/.venv ]; then
  python -m venv backend/.venv
fi
source backend/.venv/bin/activate
pip install -e .
echo "Installing backend deps done"

# Frontend
if [ ! -d frontend/node_modules ]; then
  (cd frontend && npm install)
fi

echo "Run alembic upgrade head and uvicorn"
echo "  source backend/.venv/bin/activate && alembic -c backend/alembic.ini upgrade head"
echo "  uvicorn app.main:app --reload --host 0.0.0.0 --port 8000  (from backend dir)"
echo "  cd frontend && npm run dev"
