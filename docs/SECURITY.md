# Security Review

## Authentication & Authorization
- JWT HS256, bcrypt password hashing, bearer scheme; all private routes require auth.
- `ALLOW_DEV_BYPASS` only in development; production enforces auth even on private network.
- CORS allowlist from env; cookie CSRF protection stubbed for future cookie sessions.

## Credential Handling
- Binance & ThreeRouter secrets encrypted at rest via Fernet; key stored outside DB (env), versioned.
- `never` logged or returned via API (masked status only).
- `.env` excluded from git via .gitignore.

## API Key Hardening
- Checklist before LIVE: no withdrawal permission, IP allowlist to production egress, least privilege.
- Testnet vs Live credentials separated by `environment` field.

## Transport
- Development: loopback HTTP okay; Production: HTTPS required (Nginx + Let's Encrypt or Aiven TLS).
- Aiven PG TLS `sslmode=require` enforced.

## Input Validation
- Pydantic schemas at all boundaries; `Decimal` deserialization, tick/min_notional checks.
- AI provider output treated as untrusted; JSON schema validated, prompt injection not executed.

## Risk Controls
- Hard limits `DAILY_LOSS_LIMIT`, `MAX_DRAWDOWN_PCT`, etc. must be >0 before engine starts; missing → HALTED_RISK.
- Emergency stop blocks entries immediately, applies flatten policy, audit logged.

## Logging
- Structured logs with `RedactingFilter` for api_key, secret, password, bearer tokens.
- SystemLogs & AuditEvents persisted with redacted messages.

## Known Limitations
- Dashboard is single-operator; multi-tenant not in scope.
- No WAF/DDOS beyond standard infra; recommend Cloudflare or Aiven firewall for production.
