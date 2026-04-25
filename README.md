# Projet Action

App mobile d'analyse boursière pour débutants français.

## Stack

| Couche | Techno |
|--------|--------|
| Backend | FastAPI + uvicorn (Python 3.12) |
| Frontend | Expo React Native |
| Base de données | PostgreSQL 16 |
| Cache | Redis 7 |
| Données | yfinance + Financial Modeling Prep |

---

## Démarrage rapide

### Prérequis

- [Docker Desktop](https://docs.docker.com/desktop/) ≥ 4.x
- `docker compose` v2 (`docker compose version`)

### 1. Copier et renseigner les variables d'environnement

```bash
cp .env.example .env
# Éditer .env : au minimum POSTGRES_PASSWORD
```

### 2. Lancer la stack

```bash
docker compose up --build
```

L'API est disponible sur **http://localhost:8000**.  
Documentation Swagger : **http://localhost:8000/docs**

### 3. Vérifier que tout tourne

```bash
curl http://localhost:8000/health
# {"status":"ok","timestamp":"..."}
```

---

## Commandes utiles

| Action | Commande |
|--------|----------|
| Démarrer en arrière-plan | `docker compose up -d` |
| Stopper | `docker compose down` |
| Voir les logs de l'API | `docker compose logs -f api` |
| Ouvrir Adminer (inspecteur DB) | `docker compose --profile tools up adminer` |
| Rebuild l'image API | `docker compose build api` |
| Reset complet (volumes inclus) | `docker compose down -v` |

---

## Adminer (inspecteur de base de données)

Adminer n'est pas démarré par défaut. Activer le profil `tools` :

```bash
docker compose --profile tools up
```

Puis ouvrir **http://localhost:8080**.  
Paramètres de connexion :

| Champ | Valeur |
|-------|--------|
| Système | PostgreSQL |
| Serveur | `db` |
| Utilisateur | valeur de `POSTGRES_USER` dans `.env` |
| Mot de passe | valeur de `POSTGRES_PASSWORD` dans `.env` |
| Base de données | valeur de `POSTGRES_DB` dans `.env` |

---

## Architecture Docker

```
docker-compose.yml
├── api          FastAPI (hot-reload, port 8000)
├── db           PostgreSQL 16 (volume postgres_data)
├── cache        Redis 7 (volume redis_data, 256 Mo max)
└── adminer      Adminer (profil tools, port 8080)

backend/
└── Dockerfile   Multi-stage : deps → dev → prod
```

> **Note** : PostgreSQL et Redis sont inclus pour la roadmap (persistance SQL, cache distribué).  
> Le code actuel utilise un cache fichier local (`.cache/`) et un stockage JSON (`analyses_history.json`).  
> Ces fichiers sont montés en volume dans le container `api` et persistent entre les redémarrages.

---

## Développement local sans Docker

```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

---

## Endpoints API

| Méthode | Route | Description |
|---------|-------|-------------|
| GET | `/health` | Health check |
| GET | `/analyze/{ticker}` | Analyse complète en JSON |
| GET | `/analyze/{ticker}/stream` | Analyse avec progression SSE |
| GET | `/search?q=...` | Recherche de tickers |
| GET | `/analyses` | Historique des analyses |

---

## Troubleshooting

**`POSTGRES_PASSWORD requis dans .env`**  
→ Vérifier que `.env` contient `POSTGRES_PASSWORD=<valeur>`.

**Port 8000 déjà utilisé**  
→ Modifier `API_PORT` dans `.env` (ex : `API_PORT=8001`).

**`docker compose` introuvable**  
→ Utiliser `docker-compose` (v1) ou mettre à jour Docker Desktop.

**L'API démarre mais retourne des erreurs 500**  
→ `docker compose logs api` pour voir le traceback complet.
