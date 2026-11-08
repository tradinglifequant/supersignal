# Production Deployment — Aiven

## Database (Aiven PostgreSQL)

1. Create Aiven PostgreSQL service (choose region, plan, TLS enforced).
2. Note `DATABASE_URL` with `sslmode=require`.
3. Run migrations from deploy host:
   ```bash
   DATABASE_URL="postgresql+psycopg://..." alembic upgrade head
   ```
4. Verify TLS:
   ```bash
   psql "$DATABASE_URL" -c "select version();"
   ```

## Application Runtime — Two Options

### Option A: Aiven Runtime
- Connect GitHub repo to Aiven Runtime.
- Build uses `deploy/Dockerfile.backend` + static frontend hosted separately or via Runtime static.
- Set environment variables from `.env.example` (secrets via Aiven secrets).
- Configure domain & HTTPS.
- Verify health/readiness: `/api/health`, `/api/ready`.

### Option B: Separate VPS/Container Host
- Provision VPS (Ubuntu + Docker).
- Clone repo, set `.env` with Aiven `DATABASE_URL` and production secrets.
- `docker-compose up -d --build`
- Configure Nginx + Let's Encrypt for HTTPS.
- Verify logs do not contain secrets, withdrawal disabled on Binance key, IP allowlist set.

## Post-deploy Checks (Phase 9 Exit Gate)

- [ ] TLS to Aiven PG verified
- [ ] Alembic migrations applied
- [ ] One trading worker only (check `docker ps` / Runtime scale=1)
- [ ] Health/readiness green
- [ ] Binance read-only account check passes
- [ ] No secrets in logs
- [ ] Backup/restore rehearsal

## Controlled Live Activation (Phase 10)

- Review `rules.md` risk limits
- Set minimal allocation (3 USDT) and conservative limits
- Test emergency stop
- Monitor every trade & protection state before increasing allocation
