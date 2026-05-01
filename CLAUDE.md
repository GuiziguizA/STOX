# Projet Action — Finance Corp

App mobile d'analyse boursiere pour debutants francais.

## Stack

- **Backend** : FastAPI (Python 3.12), SQLAlchemy async, Alembic, asyncpg, Redis, yfinance, pytest
- **Frontend** : Next.js 16 (App Router), React 19, TypeScript, Tailwind 4, react-hook-form, zod, recharts
- **Infra** : docker-compose (Postgres 16, Redis 7, FastAPI, Next.js)

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

## Regles absolues

1. **Ne JAMAIS inventer** d'information absente du repo ou du vault — signaler quand la donnee manque
2. **Ne JAMAIS modifier `C:\dev\cerveau\raw\`** (espace humain immutable)
3. **Workflow lean** : pas de fichier `.md` de rapport gratuit, pas de commentaire de code superflu
4. **Reponses en francais** (parametre global `language: Francais`)

## Source des skills/agents/rules

Les composants `.claude/{rules,skills,agents,commands}/` viennent de [everything-claude-code v2.0.0-rc.1](https://github.com/affaan-m/everything-claude-code) (cache local `~/.claude/plugins/cache/everything-claude-code/...`). Le plugin global est **disabled** intentionnellement — seule cette copie locale est active sur ce workspace.
