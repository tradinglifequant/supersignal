# ADR 0002: Local operator authentication boundary

## Status

Accepted for the experimental single-process prototype, not a production security approval.

## Decision

Require authentication for all data and control routes in every environment. Public endpoints are liveness/readiness, login, root and API documentation. Require a configured bcrypt operator password hash (cost 12–16) and non-default signing secret; fail closed when they are missing. Require signed, expiring tokens for the configured operator. A process-wide bounded login throttle provides basic protection for local use, not a substitute for distributed rate limiting.

Keep browser session tokens in memory rather than persistent browser storage. The dashboard sends its token in the first WebSocket message after connecting; it is never placed in the URL. The server checks an exact configured Origin before accepting a connection, requires authentication within five seconds, and closes the socket when the token expires. Vite proxies both HTTP and WebSocket requests using the browser's current origin.

## Consequences and limitations

Reloading the page requires signing in again. Logout clears the browser's copy but does not revoke already issued tokens. The in-memory rate limiter resets on restart, is shared by all clients and does not coordinate workers; production requires a reviewed shared limiter and revocable sessions. TLS, secret storage, secure proxy configuration, browser security controls and an end-to-end security review remain required. No conclusion is drawn about live or testnet trading readiness, and the Binance entry lock remains in place.
