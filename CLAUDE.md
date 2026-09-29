# Projet Action — Finance Corp

App mobile d'analyse boursiere pour debutants francais.

## Stack

- **Backend** : FastAPI (Python 3.12), SQLAlchemy async, Alembic, asyncpg, Redis, yfinance, pytest
- **Frontend** : Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, react-hook-form, zod, recharts
- **Infra** : docker-compose (Postgres 16, Redis 7, FastAPI, Next.js, **nginx reverse proxy**)

## Reseau Docker — single origin via nginx

Tous les services tournent sur le reseau `app-net`. Le **navigateur ne parle qu'a nginx** (`http://localhost`, port 80) qui route en interne vers `api:8000` ou `web:3000` via DNS Docker.

- **Tester via `http://localhost`** (port 80, pas `:8000` ni `:3000`). Les ports 8000/3000 restent exposes en dev pour debug direct mais ne doivent PAS etre la cible des appels frontend.
- Le frontend appelle des **URLs relatives** (ex: `/api/v1/auth/me`) — `NEXT_PUBLIC_API_URL` est volontairement **vide** dans `.env`. Voir `frontend/lib/config.ts`.
- Le code Next.js cote serveur (`proxy.ts` middleware) utilise `INTERNAL_API_URL=http://api:8000` (DNS Docker, jamais inline dans le bundle browser).
- Config nginx : `nginx/nginx.dev.conf` (dev) et `nginx/nginx.prod.conf` (prod, TLS + HSTS).
- Prod : `docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build` — coupe les ports host pour api/web/db, garde uniquement 80/443 sur nginx.

Le backend FastAPI utilise `ProxyHeadersMiddleware` pour que `request.client.host` reflete la vraie IP client (essentiel pour le rate-limit, qui keye par IP).

## Conventions

- **Backend** : suivre `.claude/rules/python/` (PEP 8, type hints, ruff, black, async/await)
- **Frontend** : suivre `.claude/rules/typescript/` (strict TS, App Router, Server Components par defaut)
- **Migrations Alembic** : ne JAMAIS editer une migration deja appliquee — toujours en creer une nouvelle (`alembic revision --autogenerate -m "description"`)
- **Tests** : pytest pour backend, Vitest/Playwright pour frontend (a confirmer selon ce qui est en place)

## Memoire externe — vault Obsidian

Le vault `C:\dev\cerveau` est la memoire externe (cf `~/.claude/CLAUDE.md` pour les regles completes).

- Notes brutes finance : `C:\dev\cerveau\raw\notes\finance\` (immutable, espace humain)
- Decisions/recherches : `C:\dev\cerveau\wiki\Intelligence\`
- Index a lire en premier : `C:\dev\cerveau\wiki\index.md`

## Workflow

| Etape | Action |
|---|---|
| Debut session | `/prime` (auto via hook SessionStart) — charge le contexte vault |
| Avant feature | `/query "<theme>"` (vault) + skill `search-first` (code) |
| Plan feature | agent `planner` ou `/plan` |
| Code backend | rules `python/*` actives en arriere-plan ; skill `python-patterns` si besoin |
| Tests | skill `tdd-workflow` + skill `python-testing` |
| Migration DB | skill `database-migrations` |
| Avant PR | agent `python-reviewer` puis `code-reviewer` ; `/code-review` |
| Avant deploy | agent `security-reviewer` ou `/security-review` |
| Fin session | `/save` (auto-rappele par hook Stop) — ecrit dans `cerveau/wiki/Daily/` |

## CI GitHub Actions — submodules privés

- Le dépôt STOX est **public**, mais ses trois submodules (`projet-action-backend`, `projet-action-frontend`, `stox-mobile`, tous chez `GuiziguizA`) sont **privés** : le `GITHUB_TOKEN` de la CI ne peut pas les lire.
- Les checkouts de la CI utilisent le `GITHUB_TOKEN` par défaut avec `submodules: false` : les submodules ne sont jamais téléchargés, avec ou sans secret.
- Seul le job `submodule-sanity` utilise le secret `SUBMODULES_TOKEN` (PAT fine-grained, Contents: Read-only, limité à ces trois dépôts) pour faire un `git fetch` du SHA pointé par chaque submodule. Sans ce secret, le job passe avec un avertissement (`::warning`), sans faire échouer la CI.
- **Le PAT expire** : penser à le renouveler (même nom de secret), sinon seule la vérification des pointeurs est ignorée.
- Avant de conclure qu'une PR casse la CI, vérifier si `master` échoue déjà : `gh run list --branch master`.
- Tout nouveau workflow qui fait un checkout doit gérer les submodules privés : garder `submodules: false`, ne jamais utiliser `submodules: true` sans accès aux dépôts, sinon il échoue au checkout.

## Regles absolues

1. **Ne JAMAIS inventer** d'information absente du repo ou du vault — signaler quand la donnee manque
2. **Ne JAMAIS modifier `C:\dev\cerveau\raw\`** (espace humain immutable)
3. **Workflow lean** : pas de fichier `.md` de rapport gratuit, pas de commentaire de code superflu
4. **Reponses en francais** (parametre global `language: Francais`)

## Source des skills/agents/rules

Les composants `.claude/{rules,skills,agents,commands}/` viennent de [everything-claude-code v2.0.0-rc.1](https://github.com/affaan-m/everything-claude-code) (cache local `~/.claude/plugins/cache/everything-claude-code/...`). Le plugin global est **disabled** intentionnellement — seule cette copie locale est active sur ce workspace.
