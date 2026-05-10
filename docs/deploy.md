# Deploiement Coolify

## Prerequis

- Serveur avec Coolify installe (>= v4)
- Domaine pointant sur le serveur (record A/AAAA), ex: `stox.example.com`
- Acces admin au repo GitHub `GuiziguizA/STOX` + aux 2 submodules
- Compte Resend avec domaine expediteur verifie (cle API)

## Setup initial Coolify

1. **Creer une app** : Coolify UI → New Resource → Docker Compose
2. **Source Git** :
   - URL : `https://github.com/GuiziguizA/STOX.git`
   - Branche : `master`
   - Activer **"Build with submodules"** (Coolify lance `git submodule update --init --recursive`)
3. **Compose files** : `docker-compose.yml,docker-compose.prod.yml`
4. **Domaine** : ajouter `stox.example.com` mappe sur le service `proxy` port 443. Coolify gere Let's Encrypt automatiquement.
5. **Webhook GitHub** : Coolify genere un webhook URL → coller dans GitHub repo Settings → Webhooks (events: push). A chaque push sur `master`, Coolify redeploie.
6. **Volumes persistants** : `postgres_data` et `redis_data` sont declares dans le compose, Coolify les gere. Configurer une **sauvegarde reguliere** de `postgres_data` via le plugin Coolify backups (S3 ou rsync).

## Generer les secrets

```bash
# SECRET_KEY (32 hex bytes)
python -c "import secrets; print(secrets.token_hex(32))"

# CRON_SECRET (idem)
python -c "import secrets; print(secrets.token_hex(32))"

# POSTGRES_PASSWORD (24 chars urlsafe)
python -c "import secrets; print(secrets.token_urlsafe(24))"
```

## Variables d'environnement (Coolify UI)

| Variable | Valeur attendue | Notes |
|---|---|---|
| `APP_ENV` | `production` | Active le validator strict (`config.py:_validate_production_secrets`) |
| `SECRET_KEY` | hex 64 chars | Refuse la valeur par defaut au boot |
| `POSTGRES_DB` | `stox` (au choix) | |
| `POSTGRES_USER` | `stox` (au choix) | |
| `POSTGRES_PASSWORD` | secret | Refuse `changeme` au boot |
| `CRON_SECRET` | hex 64 chars | Vide refuse en prod |
| `RESEND_API_KEY` | `re_...` | Vide refuse en prod |
| `EMAIL_FROM` | `STOX <noreply@stox.example.com>` | |
| `EMAIL_REPLY_TO` | `support@stox.example.com` | |
| `CORS_ORIGINS` | `https://stox.example.com` | HTTPS obligatoire (validator) |
| `FRONTEND_URL` | `https://stox.example.com` | |
| `FMP_API_KEY` | optionnel | Fallback FMP pour scraper actions |

**Ne PAS configurer** :
- `SMTP_HOST`, `SMTP_PORT` → laisser vides en prod pour que Resend prenne la main
- `MAILPIT_*` → dev uniquement
- `API_PORT`, `WEB_PORT`, `PROXY_HTTP_PORT` → ports caches en prod (override dans `docker-compose.prod.yml`)

## Migrations Alembic

Le service `migrate` du compose tourne en one-shot avant `api` (`depends_on: service_completed_successfully`). Aucune action manuelle au deploy.

Pour reset manuel ou downgrade :

```bash
# Coolify UI → Terminal du container api
alembic upgrade head           # avancer
alembic downgrade -1           # revenir en arriere
alembic current                # version courante
```

## Verification post-deploy

```bash
curl -fI https://stox.example.com/health   # 200 OK
curl -fI https://stox.example.com/         # 200 (frontend)
```

Test email transactionnel :
```bash
curl -X POST https://stox.example.com/auth/forgot-password \
  -H "Content-Type: application/json" \
  -d '{"email":"test@stox.example.com"}'
# → email visible dans le dashboard Resend
```

## Logs & debug

Via Coolify UI → "Logs" par service. Ou shell :

```bash
docker compose logs api --tail 100
docker compose logs proxy --tail 50
docker compose exec api alembic current
docker compose restart proxy   # apres rebuild api (sinon DNS perime)
```

## Rollback

**Methode 1 — Coolify** : Coolify garde les N derniers builds, bouton "Rollback" dans l'UI.

**Methode 2 — Git** : revert le commit umbrella + push, le webhook redeploie automatiquement.

```bash
git revert <SHA-mauvais>
git push origin master
```

## Flux CI → Coolify

```
PR backend  → GHA backend ci.yml (ruff + black + pytest --cov >= 80%)
PR frontend → GHA frontend ci.yml (eslint + tsc + vitest --coverage + playwright)
PR umbrella → GHA umbrella ci.yml (compose config + submodule sanity)

merge master umbrella
   │
   ▼
GitHub webhook → Coolify
   │
   ▼
git clone --recurse-submodules
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```
