# Projet Action

App mobile d'analyse boursière pour débutants français — V4 v2.

## Stack

| Couche | Techno |
|--------|--------|
| Backend | FastAPI + SQLAlchemy + Alembic (Python 3.12) |
| Frontend | Next.js 15 |
| Base de données | PostgreSQL 16 (pgcrypto + citext) |
| Cache | Redis 7 |
| Auth | Sessions cookie maison (Argon2id + SHA-256) |

---

## Démarrage rapide (1 commande)

### Prérequis

- [Docker Desktop](https://docs.docker.com/desktop/) ≥ 4.x
- `docker compose` v2

### 1. Variables d'environnement

```bash
cp .env.example .env
# Éditer .env — au minimum : POSTGRES_PASSWORD et SECRET_KEY
```

Générer une `SECRET_KEY` sécurisée :

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

### 2. Lancer la stack complète

```bash
docker compose up --build
```

- API : **http://localhost:8000** — Swagger : **http://localhost:8000/docs**
- Frontend : **http://localhost:3000**

### 3. Appliquer les migrations (première fois)

```bash
docker compose run --rm api alembic upgrade head
```

Cela crée les 10 tables, les enums, les index, les triggers, et insère le seed initial (4 rôles + 8 permissions).

### 4. Vérifier

```bash
curl http://localhost:8000/health
# {"status":"ok","version":"4.0.0"}
```

---

## Commandes utiles

| Action | Commande |
|--------|----------|
| Démarrer en arrière-plan | `docker compose up -d` |
| Stopper | `docker compose down` |
| Logs API | `docker compose logs -f api` |
| Logs Frontend | `docker compose logs -f web` |
| Adminer (inspecteur DB) | `docker compose --profile tools up adminer` |
| Rebuild image API | `docker compose build api` |
| **Reset BDD complet** | `docker compose down -v && docker compose up -d db && docker compose run --rm api alembic upgrade head` |

---

## Migrations Alembic

```bash
# Appliquer toutes les migrations
docker compose run --rm api alembic upgrade head

# Revenir à l'état vierge (downgrade total)
docker compose run --rm api alembic downgrade base

# Créer une nouvelle migration (hors scope FIN-57)
docker compose run --rm api alembic revision -m "description"

# Historique
docker compose run --rm api alembic history
```

---

## Tests d'intégration

```bash
# Lancer les tests après avoir appliqué les migrations
docker compose run --rm \
  -e DATABASE_URL=postgresql://postgres:${POSTGRES_PASSWORD}@db:5432/projet_action \
  api pytest tests/test_integration.py -v
```

---

## Architecture Docker

```
docker-compose.yml
├── db        PostgreSQL 16 (volume postgres_data)
├── cache     Redis 7 (volume redis_data, 256 Mo max)
├── api       FastAPI — hot-reload (port 8000)
├── web       Next.js — dev (port 3000)
└── adminer   Adminer (profil tools, port 8080)

backend/
├── alembic/          Migrations SQL
│   └── versions/
│       └── 0001_initial_schema.py
├── alembic.ini
├── app/
│   └── core/         Config + DB engine
├── main.py           Point d'entrée FastAPI
└── requirements.txt
```

---

## Adminer

```bash
docker compose --profile tools up
# Ouvrir http://localhost:8080
# Serveur : db  |  User : POSTGRES_USER  |  DB : POSTGRES_DB
```

---

## Troubleshooting

**`POSTGRES_PASSWORD requis dans .env`**  
→ Vérifier que `.env` contient `POSTGRES_PASSWORD=<valeur>`.

**Port déjà utilisé**  
→ Modifier `API_PORT`, `WEB_PORT` ou `ADMINER_PORT` dans `.env`.

**`alembic upgrade head` échoue (extension pgcrypto manquante)**  
→ Vérifier que Postgres tourne : `docker compose ps db`.

**L'API ne démarre pas**  
→ `docker compose logs api` pour voir l'erreur complète.
