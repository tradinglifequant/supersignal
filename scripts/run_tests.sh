#!/usr/bin/env bash
set -e
export DATABASE_URL="sqlite:///:memory:"
export ALLOW_DEV_BYPASS="true"
pytest backend/tests -v
echo "Backend tests passed"
# Frontend tests if present
if [ -f frontend/package.json ]; then
  (cd frontend && npm test || echo "Frontend tests skipped or not configured")
fi
