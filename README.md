# Projet Action

App mobile d'analyse boursière pour débutants français — V4 v2.

## Stack

| Couche | Techno |
|--------|--------|
| Backend | FastAPI + SQLAlchemy 2 (async) + Alembic (Python 3.12) |
| Frontend | Next.js 16 (App Router, React 19, TypeScript, Tailwind 4) |
| Base de données | PostgreSQL 16 (pgcrypto + citext) |
| Cache | Redis 7 (cache yfinance + rate-limit IP) |
| Auth | Sessions cookie maison (Argon2id pour les passwords, SHA-256 pour les tokens) |
| Reverse proxy | nginx 1.27 (single-origin sur port 80) |

---

## Démarrage rapide

### Prérequis

- [Docker Desktop](https://docs.docker.com/desktop/) ≥ 4.x avec `docker compose` v2.

### 1. Variables d'environnement

```bash
cp .env.example .env
```

À renseigner au minimum dans `.env` :

```bash
POSTGRES_PASSWORD=postgres        # ⚠️ Doit matcher le password réel du volume DB
SECRET_KEY=<32 octets hex>        # python -c "import secrets; print(secrets.token_hex(32))"
CORS_ORIGINS=http://localhost     # CSV ou single — voir section CORS plus bas
```

### 2. Lancer toute la stack

```bash
docker compose up --build -d
```

Premier démarrage uniquement — appliquer les migrations Alembic :

```bash
docker exec projet_action_api alembic upgrade head
```

### 3. Vérifier

```bash
curl http://localhost/health
# {"status":"ok","env":"development"}
```

✅ **Toujours tester via `http://localhost` (port 80, le reverse proxy nginx)**.
Les ports `:8000` (API) et `:3000` (frontend) restent exposés en dev pour debug uniquement — **ne pas les utiliser** pour les tests fonctionnels.

---

## Architecture Docker

```
                ┌──────────────────┐
   browser ───► │ nginx (proxy)    │ port 80 ─── single origin (cookies, CSRF, CORS)
                │ projet_action_   │
                │ proxy            │
                └─────┬─────┬──────┘
                      │     │
            DNS Docker│     │DNS Docker
                      ▼     ▼
              ┌──────────┐ ┌──────────┐
              │ api:8000 │ │ web:3000 │
              │ FastAPI  │ │ Next.js  │
              └─────┬────┘ └────┬─────┘
                    │           │
                    └─┬─────────┘
                      │
                ┌─────▼─────┐ ┌─────────┐
                │ db:5432   │ │ cache:  │
                │ Postgres  │ │ 6379    │
                │           │ │ Redis   │
                └───────────┘ └─────────┘
```

| Service | Container | Image | Rôle | Port host |
|---|---|---|---|---|
| `proxy` | `projet_action_proxy` | nginx:1.27-alpine | Reverse proxy, single-origin | **80** |
| `api` | `projet_action_api` | build `./backend` | FastAPI (uvicorn `--reload`) | 8000 (debug) |
| `web` | `projet_action_web` | build `./frontend` | Next.js dev | 3000 (debug) |
| `db` | `projet_action_db` | postgres:16-alpine | PostgreSQL | 5432 |
| `cache` | `projet_action_cache` | redis:7-alpine | Cache + rate-limit | (interne) |
| `adminer` | `projet_action_adminer` | adminer:latest | Inspecteur DB | 8080 |

`proxy` a `depends_on: api: service_healthy` — il **ne démarre pas** tant que l'API n'est pas saine. Si tu vois `dependency failed to start: container projet_action_api is unhealthy`, regarde **d'abord les logs API** (cf. troubleshooting).

---

## Routing nginx (`nginx/nginx.dev.conf`)

```
http://localhost/health                       → api:8000/health
http://localhost/api/v1/<auth|users|roles|gdpr|purge>/...
http://localhost/<auth|users|roles|permissions|analyze|search|analyses>/...
                                              → api:8000 (sans rewrite du path)
http://localhost/analyze/.../stream           → api:8000 SSE (proxy_buffering off)
http://localhost/_next/webpack-hmr            → web:3000 (websocket)
http://localhost/                             → web:3000 (Next.js — toutes les autres routes)
```

Notes :
- nginx ne réécrit pas le path : `/api/v1/auth/me` → `api:8000/api/v1/auth/me`
- Les routes `auth/users/roles/gdpr/purge` sont incluses avec `prefix="/api/v1"` côté FastAPI
- Les routes `analyze/search/analyses/health` sont à la racine côté FastAPI (sans préfixe)
- Le frontend appelle des URLs **relatives** (`/api/v1/auth/me`) — `NEXT_PUBLIC_API_URL` est volontairement vide
- Le code Next.js server-side (middleware `proxy.ts`) utilise `INTERNAL_API_URL=http://api:8000` (DNS Docker)

### Reverse proxy headers

Le backend uvicorn est lancé avec :

```bash
uvicorn app.main:app --proxy-headers --forwarded-allow-ips=*
```

Cela fait confiance aux headers `X-Forwarded-For` envoyés par nginx pour que `request.client.host` reflète la **vraie IP client** — essentiel parce que le rate-limit keye par IP. Sans ça, toutes les requêtes paraîtraient venir du container nginx.

---

## Migrations Alembic

Les migrations sont dans `backend/alembic/versions/`. Au premier démarrage et après tout `pull`, il faut les appliquer :

```bash
docker exec projet_action_api alembic upgrade head
```

| Action | Commande |
|---|---|
| Voir la version courante | `docker exec projet_action_api alembic current` |
| Historique complet | `docker exec projet_action_api alembic history` |
| Appliquer toutes les migrations | `docker exec projet_action_api alembic upgrade head` |
| Reculer d'un cran | `docker exec projet_action_api alembic downgrade -1` |
| Reset complet | `docker exec projet_action_api alembic downgrade base` |
| Créer une nouvelle migration | `docker exec projet_action_api alembic revision --autogenerate -m "description"` |

⚠️ **Ne jamais éditer une migration déjà appliquée** — toujours en créer une nouvelle.

⚠️ Les enums PostgreSQL contiennent des valeurs avec **points** (ex: `user.register`). Côté Python, l'`AuditEventType` a des `name` avec `_` (ex: `user_register`) mappés vers les `value` avec `.`. Le mapping SQLAlchemy passe par `values_callable=lambda obj: [e.value for e in obj]` (cf. [`backend/app/models/audit.py`](backend/app/models/audit.py)) — sans ça, SQLAlchemy enverrait le `name` qui ne match pas l'enum DB.

---

## Auth flow

```
1. POST /api/v1/auth/register   { email, password, first_name, last_name }
   → 201 + Set-Cookie: cc_session=..., cc_csrf=...
   → status user = "pending" (email à vérifier)

2. (dev) Activer le compte manuellement :
   docker exec -e PGPASSWORD=postgres projet_action_db \
     psql -U postgres -d projet_action \
     -c "UPDATE users SET status='active', email_verified_at=now() WHERE email='<email>';"

3. POST /api/v1/auth/login      { email, password }
   → 200 + Set-Cookie: cc_session=..., cc_csrf=...

4. GET /analyses                  (avec cookies)
   → 200 + liste JSON
```

Le cookie `cc_session` est `HttpOnly` — il ne fuit pas au JavaScript. Le cookie `cc_csrf` est lu par le client et renvoyé via le header `x-csrf-token` sur chaque mutation (double-submit pattern, cf. [`backend/app/core/deps.py`](backend/app/core/deps.py) `require_csrf`).

**Rate-limit register** : 3 inscriptions/heure par IP ([`backend/app/api/v1/auth.py`](backend/app/api/v1/auth.py) `register`). Pour le purger en dev :

```bash
docker exec projet_action_cache redis-cli FLUSHDB
```

---

## CORS

Géré côté FastAPI ([`backend/app/main.py`](backend/app/main.py)). En dev avec nginx single-origin, `CORS_ORIGINS=http://localhost` suffit (browser → nginx → API, même origine du point de vue browser).

Format accepté dans `.env` :
- CSV : `CORS_ORIGINS=http://localhost,https://staging.example.com`
- Une seule valeur : `CORS_ORIGINS=http://localhost`

⚠️ Le validator `_parse_cors_origins` ([`backend/app/core/config.py`](backend/app/core/config.py)) gère le CSV. Le field utilise `Annotated[list[str], NoDecode]` pour empêcher pydantic-settings 2.x de tenter un `json.loads` sur la string brute (sinon `JSONDecodeError`).

En production, `_validate_production_secrets` impose des origines en `https://` et refuse `*`.

---

## Production

```bash
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
```

Le compose prod :
- Coupe les ports host pour `api`, `web`, `db` (nginx est seul exposé sur **80** et **443**)
- Active TLS + HSTS dans `nginx/nginx.prod.conf`
- Lance uvicorn sans `--reload`, avec `--workers 2`

`Settings._validate_production_secrets` fait crasher l'app au boot si :
- `secret_key` a la valeur par défaut
- `postgres_password` a la valeur par défaut
- `cron_secret` ou `resend_api_key` sont vides
- `cors_origins` contient `*` ou des origines non-HTTPS

---

## Commandes utiles

| Action | Commande |
|---|---|
| Démarrer en arrière-plan | `docker compose up -d` |
| Stopper | `docker compose down` |
| Stopper + supprimer volumes (⚠️ reset DB) | `docker compose down -v` |
| Logs API | `docker compose logs -f api` |
| Logs nginx | `docker compose logs -f proxy` |
| Rebuild image API | `docker compose build api` |
| Force restart d'un service | `docker compose restart api` |
| Adminer (inspecteur DB) | http://localhost:8080 — Serveur : `db`, User : `postgres`, DB : `projet_action` |
| Shell dans l'API | `docker exec -it projet_action_api sh` |
| Purger le rate-limit | `docker exec projet_action_cache redis-cli FLUSHDB` |
| Tests pytest | `docker exec projet_action_api pytest -v` |

---

## Troubleshooting

### `dependency failed to start: container projet_action_api is unhealthy`

L'API a crashé au démarrage. Voir les logs :

```bash
docker logs projet_action_api --tail 80
```

Causes connues :
- **Mauvais password Postgres** : `asyncpg.exceptions.InvalidPasswordError`. Le `POSTGRES_PASSWORD` de `.env` doit matcher celui avec lequel le volume `postgres_data` a été initialisé. Si ça matche pas, soit corriger `.env`, soit `docker compose down -v && docker compose up -d` (⚠️ supprime les données).
- **Variable env manquante** : `pydantic_settings.exceptions.SettingsError`. Vérifier `.env` complet.
- **Migration non appliquée** : `relation "users" does not exist`. Lancer `docker exec projet_action_api alembic upgrade head`.

### Healthcheck `(unhealthy)` mais l'app répond en 200

Faux positif cosmétique : `curl` n'est pas dans `python:3.12-slim` (image API), et `wget` peut foirer sur IPv6 dans nginx alpine. L'app fonctionne. Pour fixer :
- API : `apt-get install -y curl` dans le Dockerfile, ou utiliser `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"`
- Proxy : remplacer le test par `wget -qO- -4 http://127.0.0.1/health`

### Port 80 déjà utilisé

```bash
PROXY_HTTP_PORT=8080 docker compose up -d
```

Puis tester sur `http://localhost:8080`.

### 429 Too Many Requests sur `/api/v1/auth/register`

Rate-limit : 3 inscriptions/heure par IP. Purger :

```bash
docker exec projet_action_cache redis-cli FLUSHDB
```

### 404 sur `http://localhost:3000/<route>`

Tu testes le port frontend direct au lieu du reverse proxy. Toujours utiliser **`http://localhost`** (port 80). Le port 3000 ne route pas les `/api/v1/...` parce que Next.js ne sait pas router vers le backend tout seul — c'est nginx qui le fait.

### `relation "users" does not exist`

Migrations non appliquées. Voir section Migrations Alembic.

### `can't subtract offset-naive and offset-aware datetimes` au flush

Mismatch tz entre Python et PostgreSQL. Vérifier que [`backend/app/core/db.py`](backend/app/core/db.py) `Base` a :

```python
type_annotation_map = {datetime: DateTime(timezone=True)}
```

Sans ça, SQLAlchemy mappe `Mapped[datetime]` vers `TIMESTAMP` (sans tz) alors que la DB a des colonnes `TIMESTAMPTZ` créées par les migrations.

---

## Structure du repo

```
.
├── docker-compose.yml          # Stack dev (api, web, db, cache, adminer, proxy)
├── docker-compose.prod.yml     # Override prod (TLS, ports cachés, --workers 2)
├── nginx/
│   ├── nginx.dev.conf          # Routing dev (HTTP nu sur 80)
│   └── nginx.prod.conf         # Routing prod (HTTPS + HSTS)
├── backend/
│   ├── Dockerfile              # Multi-stage : deps → dev → prod
│   ├── requirements.txt
│   ├── alembic.ini
│   ├── alembic/
│   │   ├── env.py              # Surcharge sqlalchemy.url depuis settings
│   │   └── versions/
│   │       ├── 0001_initial_schema.py
│   │       └── 0002_rgpd_audit_event_types.py
│   ├── api/
│   │   └── routes.py           # Routes analyze/search/analyses/health (racine, sans prefix)
│   └── app/
│       ├── main.py             # FastAPI app, middlewares, routers
│       ├── api/v1/             # Routes /api/v1/* (auth, users, roles, gdpr, purge)
│       ├── core/
│       │   ├── config.py       # Settings (pydantic-settings)
│       │   ├── db.py           # Engine async + Base + get_db
│       │   ├── deps.py         # get_current_user, require_csrf, require_permission
│       │   ├── middleware.py   # AccessLogMiddleware, RequestIDMiddleware
│       │   ├── redis.py        # Client Redis (rate-limit, cache)
│       │   └── security.py     # Argon2id, hash_token, generate_token
│       ├── models/             # SQLAlchemy ORM (User, Role, Permission, AuditLog…)
│       ├── schemas/            # Pydantic in/out
│       └── services/           # Logique métier (audit, session, email…)
└── frontend/
    ├── Dockerfile              # Multi-stage Next.js
    ├── app/                    # App Router : (public), (protected), (admin)
    ├── components/             # AnalysesTable, SearchBar, AnalysisDashboard…
    ├── hooks/                  # useAnalysis, etc.
    ├── lib/config.ts           # NEXT_PUBLIC_API_URL relative
    └── proxy.ts                # Middleware Next.js → INTERNAL_API_URL
```
