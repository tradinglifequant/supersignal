# Security status

This prototype is **not approved for public deployment or real credentials**. Binance entry is locked for both testnet and live; protective/reducing order paths are not verified against a live or testnet exchange account.

## Authentication baseline

All application data and control HTTP routes require a bearer token, including in development. Health, readiness, and login endpoints are public (OpenAPI docs are disabled when `APP_ENV=production`). Login requires an explicitly configured bcrypt `ADMIN_PASSWORD_HASH` and a unique `JWT_SECRET_KEY` of at least 32 characters. There is no default password or development bypass. Tokens require an expiration, the configured operator subject, and an optional `jti` claim used for in-process revocation on `POST /api/auth/logout`. The frontend keeps the token only in memory, and authenticates WebSockets using the first message rather than the URL; WebSocket origins must exactly match the configured CORS allowlist and sessions close on token expiration or `jti` revocation.

Login is limited to 10 attempts per 60 seconds per process, across all clients. Both login throttling and `jti` revocation are bounded in-memory safeguards for a single-process local prototype: they reset on process restart and do not coordinate across multiple workers. Deployment requires an independently reviewed shared rate limiter, TLS, a secure trusted proxy setup, and persistent distributed session revocation.

## Credential & logging protections

- Encrypted exchange credentials require an explicit `CREDENTIALS_ENCRYPTION_KEY` when `APP_ENV=production` (failing closed if unset); development mode uses a process-cached ephemeral key if unset.
- Log formatting applies secret redaction across string and dictionary log arguments, scrubbing bearer tokens, signatures, listen keys, `X-MBX-APIKEY`, API secrets, and passwords, and `/api/ready` sanitizes database errors so connection URLs are never exposed.

## Remaining review

Endpoint authorization, configuration auditing, dependency vulnerabilities, CSP/XSS defenses, container/network isolation, and deployment all require a full independent security review before any external exposure. Account/exchange permissions and Portfolio Margin support have not been verified. See the README and phase roadmap for release blockers. Never treat passing mock tests as evidence of exchange or production readiness.
