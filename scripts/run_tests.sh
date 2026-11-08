#!/usr/bin/env bash
set -euo pipefail
export PYTHONPATH="${PYTHONPATH:+$PYTHONPATH:}backend"
if [ -x ".venv/bin/pytest" ]; then
  PYTEST_BIN=".venv/bin/pytest"
else
  PYTEST_BIN="pytest"
fi
"$PYTEST_BIN" backend/tests -v
echo "Backend tests passed"
if [ -f frontend/package.json ]; then
  (cd frontend && npm run lint && npm test && npm run build)
fi
