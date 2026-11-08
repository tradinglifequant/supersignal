# Security status

This prototype is **not approved for public deployment or real credentials**. Binance entry is locked for both testnet and live; protective/reducing order paths are not verified.

## Authentication baseline

All application data and control HTTP routes require a bearer token, including in development. Health, readiness, login and API documentation are public. Login requires an explicitly configured bcrypt `ADMIN_PASSWORD_HASH` and a unique `JWT_SECRET_KEY` of at least 32 characters. There is no default password or development bypass. Tokens require an expiration and the configured operator subject. The frontend keeps the token only in memory, and authenticates WebSockets using the first message rather than the URL; WebSocket origins must exactly match the configured CORS allowlist and sessions close at token expiration.

Login is limited to 10 attempts per 60 seconds per process, across all clients. This is bounded and protects the single-process local prototype, but it resets on restart, can be exhausted by any client, and does not coordinate across workers. Deployment requires an independently reviewed shared rate limiter, TLS, a secure trusted proxy setup, and server-side session revocation. Browser logout only clears the local token; an issued token remains valid until it expires or the signing key is rotated.

## Remaining review

Credential encryption and logging redaction, endpoint validation, configuration changes and auditing, dependencies, session management, CSP/XSS defenses, and deployment all require a full security review. Account/exchange permissions and Portfolio Margin support have not been verified. See the README and phase roadmap for release blockers. Never treat passing mock tests as evidence of exchange or production readiness.
