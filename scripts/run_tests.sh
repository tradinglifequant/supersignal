#!/usr/bin/env bash
set -e
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}backend"
pytest backend/tests -v
echo "Backend tests passed"
# Frontend tests if present
if [ -f frontend/package.json ]; then
  (cd frontend && npm test)
fi
