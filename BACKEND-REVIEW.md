# Review Backend — Projet Action

> Review effectuee par l'agent `python-reviewer` (ECC v2.0.0-rc.1) le 2026-05-01.
> Cible : `backend/` (clone `GuiziguizA/projet-action-backend`).
> Stack : FastAPI 0.111 / SQLAlchemy 2.0 async / Alembic / Argon2 / Pydantic / Redis / yfinance / pytest.

## Resume

- **Verdict** : **Warning** — CRITICAL securite + plusieurs HIGH a fixer avant deploy production
- **Fichiers analyses** : 22 fichiers Python applicatifs (hors `.venv`, `alembic/versions`, `__pycache__`)
- **Findings** : **5 CRITICAL · 14 HIGH · 11 MEDIUM**
- **Outils statiques** : ruff [missing] · mypy [missing] · bandit [missing] — review 100% manuelle

---

## Ce qui va bien

- **Crypto solide** : Argon2 bien configure (`time_cost=3, memory_cost=64MB, parallelism=4`), tokens via `secrets.token_bytes(32)` + `hashlib.sha256` stockes en `bytea`, comparaison time-safe avec `hmac.compare_digest` — `app/core/security.py:1-60`
- **CSRF double-submit cookie** correctement implemente avec compare time-safe — `app/core/deps.py:124-145`
- **Rate limit Redis** atomique via script Lua (token bucket) — pas de race condition — `app/core/redis.py:31-77`
- **Pas d'enumeration d'email** sur `/auth/forgot-password` : reponse 200 systematique — `app/api/v1/auth.py:379`
- **Eager loading systematique** avec `selectinload` pour eviter les N+1 sur `user_roles → role → role_permissions → permission` — bonne hygiene SQLAlchemy 2.0 async
- **SQLAlchemy 2.0 typing moderne** : `Mapped[...]` + `mapped_column`, queries 100% parametrees (aucun f-string dans les `where`)
- **Audit log RGPD** complet sur toutes les operations sensibles (login, logout, role change, delete, export)
- **Token storage** : on stocke uniquement `sha256(token)` en BDD, jamais le raw — `app/core/security.py:32-44`

---

## CRITICAL (a fixer avant deploy)

### Secret par defaut hardcode dans la config
- **File** : `app/core/config.py:26`
- **Issue** : `secret_key: str = "change_me_with_a_random_32_byte_hex_string"` — defaut accepte sans verification. Un deploy par megarde sans `.env` lance le serveur avec ce secret. De plus `secret_key` n'est en realite jamais utilise dans le code (seul `cron_secret` l'est) — c'est un piege en attente.
- **Fix** : en production, faire `if settings.is_production and settings.secret_key.startswith("change_me"): raise RuntimeError(...)` au boot ; idem pour `postgres_password="changeme"` et `cron_secret=""`. Mieux : marquer ces champs sans defaut et laisser pydantic-settings echouer si absents en prod.

### CORS allow_origins vide en prod par defaut + allow_credentials=True
- **File** : `app/main.py:32-39` + `app/core/config.py:29`
- **Issue** : defaut `cors_origins=["http://localhost:3000"]` couple a `allow_credentials=True` et `allow_methods=["*"]`. Si la liste reste mal configuree en prod, c'est un risque CSRF/exfiltration cookies ; `allow_origins=["*"]` avec credentials serait rejete par le navigateur — mais rien n'empeche un operateur d'y mettre `*`.
- **Fix** : valider explicitement au boot que `cors_origins` ne contient pas `*` quand `is_production`, et que toutes les origines sont en HTTPS. Restreindre `allow_methods` a la liste reelle (`GET`, `POST`, `PATCH`, `DELETE`).

### Endpoints `/analyze/*`, `/search`, `/analyses` non authentifies + sans rate limit
- **File** : `api/routes.py:110-366`
- **Issue** : tout le module `api/routes.py` est inclus directement dans `app/main.py:66` sans aucune dependance d'auth ni de rate limit. `analyze_stream` declenche un scraping yfinance (operation lourde) accessible publiquement. Porte d'entree DoS.
- **Fix** : appliquer `Depends(get_current_user)` (ou au minimum un rate limit Redis par IP) sur `/analyze/{ticker}`, `/analyze/{ticker}/stream`, `/search`. Decision a prendre selon le modele metier mais le defaut actuel est dangereux.

### Bare `except Exception: pass` qui avalent silencieusement des erreurs critiques
- **Files** :
  - `app/api/v1/auth.py:321-322` (envoi welcome email)
  - `app/api/v1/users.py:283-285` (envoi suspension email)
  - `app/api/v1/gdpr.py:71-73` (envoi deletion email)
  - `storage.py:21-22` et `storage.py:60-61` (lecture/ecriture cache)
  - `scraping/yfinance_scraper.py:47-48`, `60-61`, `312-314` (cache I/O et fetch dividends)
  - `scraping/fmp_client.py:74-75`, `86-87` (cache I/O)
  - `api/routes.py:106-107` (suggestions ticker)
- **Issue** : aucune trace dans les logs, impossible de detecter une regression en prod (Resend down, disque plein, etc.).
- **Fix** : au minimum `except Exception: logger.exception(...)`. Pour les emails, queue d'envoi async ou fail-open mais loguer en `error`.

### Endpoint `/internal/purge` accepte un secret vide + comparaison non time-safe
- **File** : `app/api/v1/purge.py:29-37`
- **Issue** : si `cron_secret` est vide, le check leve 503 — OK. Mais defaut `cron_secret: str = ""` autorise l'oubli en prod. La verification se fait via `authorization == f"Bearer {settings.cron_secret}"` avec **comparaison directe** (`!=`), pas de `secrets.compare_digest` — leak de timing theorique sur le secret.
- **Fix** :
  ```python
  if not secrets.compare_digest(authorization.encode(), expected.encode()):
  ```
  + valider au boot que `cron_secret` est non-vide en prod.

---

## HIGH (a planifier)

### Mauvaise utilisation de Pydantic Settings : `cors_origins: list[str]` ne se parse pas depuis `.env`
- **File** : `app/core/config.py:29`
- **Issue** : pydantic-settings v2 ne parse pas une liste depuis un string `.env` sans validator. La valeur reelle en prod sera la valeur par defaut, pas celle du `.env`.
- **Fix** : utiliser `Field(..., env="CORS_ORIGINS")` + un `field_validator` qui split sur `,`, ou typer en `str` puis parser en property.

### N+1 cache : `_get_full_user` re-execute la query apres `db.commit()` au lieu d'utiliser refresh
- **Files** : `app/api/v1/auth.py:81-83` + `app/api/v1/users.py:44-49`
- **Issue** : apres chaque mutation, on relit l'utilisateur complet (jusqu'a 4 niveaux de selectinload). Sur des routes a forte mutation (invite/update_user_roles), c'est 2 queries la ou un `await db.refresh(user, attribute_names=[...])` suffirait — ou simplement reutiliser l'objet deja charge avec `selectinload` initial.
- **Fix** : charger une seule fois en debut de route avec `_load_user_full`, muter, commit, retourner.

### Mutation de cookie + commit de session lors d'un simple `get_current_session` (refresh `last_seen_at`)
- **File** : `app/core/deps.py:60-68`
- **Issue** : chaque requete authentifiee declenche `UPDATE auth_sessions SET last_seen_at, idle_expires_at WHERE id = ...` + `db.commit()` **avant** que la route ne s'execute. Cela :
  1. Genere une ecriture par requete (couteux en charge)
  2. Si la route business leve une exception transaction-level, le commit du refresh reste — corrompant la coherence transactionnelle attendue
  3. Bloque toute la requete sur un round-trip DB additionnel
- **Fix** : throttler le refresh (par ex. ne refresh que si `last_seen_at < now - 60s`), et le faire **sans** `commit` explicite ou via une session DB separee. Mieux : background task FastAPI.

### `selectinload("role")` strings au lieu des relationships typees
- **Files** : `app/api/v1/auth.py:67-78`, `app/api/v1/users.py:30-41`, `app/api/v1/roles.py:34-36`
- **Issue** : `selectinload("role").selectinload("role_permissions")...` utilise des strings — perd le typage statique et casse silencieusement si on renomme la relation.
- **Fix** : `selectinload(User.user_roles).selectinload(UserRole.role).selectinload(Role.role_permissions).selectinload(RolePermission.permission)`.

### `from datetime import timedelta` importe localement plusieurs fois dans la meme fonction
- **Files** :
  - `app/api/v1/auth.py:61, 129, 348, 381, 411`
  - `app/api/v1/users.py:168`
- **Issue** : imports en plein milieu de fonction — anti-pattern PEP 8 (E402). Idem pour `from app.core.security import cookie_to_token` reimporte dans `verify_email` (`auth.py:278`) et `reset_password` (`auth.py:411`) alors que deja importe en haut.
- **Fix** : deplacer en haut du fichier.

### Acces a une fonction "private" (underscore) cross-module
- **File** : `app/api/v1/roles.py:25-27`
- **Issue** : `from app.core.deps import _get_user_permissions` — l'underscore signale prive. La logique de permissions devrait etre une dependency reutilisable ou un helper public.
- **Fix** : renommer `_get_user_permissions` → `get_user_permissions` (public) ou creer une dependency `Depends(require_any_permission(["roles.manage", "users.read"]))`.

### Mutable default argument sur `data: dict = None` dans signature
- **File** : `api/routes.py:183` — `def send(step: str, message: str, progress: int, data: dict = None) -> str`
- **Issue** : type hint declare `dict` non-Optional mais defaut `None` — incoherence et risque de bug silencieux.
- **Fix** : `data: dict | None = None` (le code teste deja `if data:` qui est OK, mais la signature ment).

### `datetime.utcnow()` deprecie en Python 3.12 + sans timezone
- **Files** :
  - `api/routes.py:366`
  - `scraping/yfinance_scraper.py:379`
  - `storage.py:65, 66`
- **Issue** : `datetime.utcnow()` est deprecie depuis Python 3.12 (DeprecationWarning) et retourne un naive datetime. Ailleurs dans le projet, `datetime.now(timezone.utc)` est correctement utilise — incoherence.
- **Fix** : remplacer par `datetime.now(timezone.utc)` partout, et serialiser via `.isoformat()`.

### Persistance JSON non-atomique + pas de lock
- **File** : `storage.py:14-27`
- **Issue** : `_load`/`_save` ne sont pas thread-safe ni protegees contre une ecriture partielle (si crash → fichier corrompu). FastAPI peut servir N requetes en parallele : deux `save_analysis` simultanes peuvent ecraser l'historique.
- **Fix** : ecrire dans un fichier temp puis `os.replace` (atomique sur Windows et POSIX) + `asyncio.Lock` global, ou migrer vers PostgreSQL puisque le stack en a deja un.

### Blocking I/O dans handler async (storage.save_analysis)
- **File** : `api/routes.py:164, 287` (save_analysis appele sync depuis async)
- **Issue** : `storage.save_analysis` fait `open(...).write(...)` bloquant dans une coroutine — peut staller le event loop sur des disques lents/network.
- **Fix** : `await asyncio.get_running_loop().run_in_executor(None, storage.save_analysis, response)` ou utiliser `aiofiles`.

### Deux fonctions `_get_user_permissions` quasi identiques
- **Files** : `app/core/deps.py:102-107` et `app/schemas/user.py:71-76` (set comprehension dupliquee)
- **Issue** : code duplique — risque de derive (un dev ajoute une regle d'un cote, oublie l'autre).
- **Fix** : factoriser dans `app/services/permissions.py`.

### `from sqlalchemy.orm import selectinload` reimport dans `verify_email`
- **File** : `app/api/v1/auth.py:313`
- **Issue** : deja importe ligne 9.
- **Fix** : supprimer.

### `_user_agent` jamais utilise dans `gdpr.py` pour l'audit (only ip_address)
- **File** : `app/api/v1/gdpr.py:67, 105-111`
- **Issue** : incoherent avec `auth.py` qui audit avec `user_agent`. Un audit RGPD sans UA est moins traceable.
- **Fix** : ajouter `user_agent=request.headers.get("user-agent")`.

### Aucune validation de force du mot de passe au-dela de la longueur
- **File** : `app/schemas/auth.py:26-31, 55-60`
- **Issue** : `len(v) >= 8` est tres faible (NIST recommande au moins absence de breach/blacklist + entropie minimale). Pas de check majuscule/minuscule/chiffre, pas de check `pwnedpasswords` (HIBP).
- **Fix** : porter le minimum a 12, refuser les passwords les plus communs (zxcvbn ou liste statique top-10000), idealement integrer HIBP k-anonymity.

---

## MEDIUM (nice to have)

### Two FastAPI apps : `main.py` racine + `app/main.py` (confusion architecturale)
- **Files** : `main.py` (racine, 23 lignes, ancien) vs `app/main.py` (le vrai entrypoint avec auth/users/etc.)
- **Issue** : `main.py` racine ne charge ni l'auth, ni Redis — c'est une vieille version laissee en place. `start_server.py:21` lance `main:app` (l'ancien, sans auth). Risque de demarrer la mauvaise app en dev/CI.
- **Fix** : supprimer `main.py` racine (et `start_server.py`) ou bien declarer clairement le module canonique et corriger `start_server.py:21` en `app.main:app`.

### `@app.on_event("shutdown")` deprecie en faveur de lifespan
- **File** : `app/main.py:54`
- **Issue** : deprecie depuis FastAPI 0.93. Ne casse pas mais sera supprime.
- **Fix** : utiliser `@asynccontextmanager async def lifespan(app): ... yield ...` puis `FastAPI(lifespan=lifespan)`.

### Logging via `logging.basicConfig` au boot du module — fragile
- **Files** : `app/main.py:17-20`, `start_server.py:9-16`
- **Issue** : `basicConfig` est no-op si deja configure. Avec uvicorn + reload, la config peut etre ecrasee.
- **Fix** : utiliser `logging.config.dictConfig` avec un fichier YAML/JSON, et configurer via `uvicorn --log-config`.

### `_get_api_key` leve `EnvironmentError` qui est juste un alias de `OSError`
- **File** : `scraping/fmp_client.py:42-47`
- **Issue** : en Python 3, `EnvironmentError == OSError` — confusion semantique.
- **Fix** : definir une exception metier `class FMPConfigError(Exception)`.

### `import logging` repete dans plusieurs modules
- **Issue** : pas un bug mais un seul `app.logging` centralise serait plus propre.

### Comparaison `if dividends is not None and not dividends.empty` puis `dividends.index.year` — pandas-dependant
- **File** : `scraping/yfinance_scraper.py:300-314`
- **Issue** : si `dividends.index` n'est pas un `DatetimeIndex` (cas exotique), `.year` plante. Le `try/except: pass` masque mais sans log.

### Magic numbers eparpilles (seuils de scoring)
- **Files** : `analysis/rentabilite.py`, `analysis/solidite.py`, `analysis/flux.py`, `analysis/valorisation.py`
- **Issue** : les seuils numeriques (10, 7, 4, 0.30, 0.60, ...) sont en dur dans chaque `if`. Ils sont bien documentes par les messages mais difficiles a tuner.
- **Fix** : extraire chaque table de seuil en `Enum` ou dataclass `ScoringThresholds` au niveau module.

### Fonctions `compute(data: dict)` typees `dict` au lieu d'un type `ScrapedData`
- **Files** : `analysis/*.py`
- **Issue** : `data: dict` en entree perd le contrat — les `data.get(...)` peuvent retourner `None` silencieusement si on renomme une cle.
- **Fix** : definir un `TypedDict` ou un `pydantic BaseModel` `ScrapedData` partage entre scrapers et analysers.

### Imports non-conformes PEP 8 dans `app/api/v1/users.py:136` (`import secrets` au milieu)
- **File** : `app/api/v1/users.py:136`
- **Issue** : `import secrets` dans `invite_user`. Idem `from datetime import timedelta` dans plusieurs handlers.
- **Fix** : deplacer en haut.

### `Header(default="")` + comparaison directe (`!=`) dans `_verify_cron`
- **File** : `app/api/v1/purge.py:29-37`
- Voir CRITICAL ci-dessus mais aussi : l'absence de header `Authorization` n'est pas distinguee d'un mauvais token (probablement voulu — bien). Cependant `default=""` plutot que `default=None` puis test rend la lecture moins claire.

### Annotations manquantes sur quelques fonctions
- **Files** :
  - `main.py:21` `def health()` (pas grave mais le module sera supprime ideal)
  - `api/routes.py:46` `def _key_metrics(data: dict, r, s, f, v) -> dict:` — `r, s, f, v` non annotes (ce sont `RentabiliteScore`, etc.)
  - `api/routes.py:48` `def fmt_pct(v, decimals=1)` — pas d'annotation
  - `app/services/session.py:18, 77, 85, 98` — `user_id`, `session_id` non annotes (devraient etre `uuid.UUID`)

### `Profile(user_id=user.id)` cree si absent dans `update_user` puis re-fetch
- **File** : `app/api/v1/users.py:217-221`
- **Issue** : au lieu de creer puis refetch, on peut directement `await db.flush()` puis muter `user.profile = new_profile` en local.

---

## Recommandations transverses

1. **Mettre en place ruff + mypy + bandit** dans `pyproject.toml` et en CI. Le projet est trop sensible (auth/RGPD) pour rester sans linter automatise. Configuration minimum :
   ```bash
   ruff check --select=E,F,W,I,UP,S,B,C4,SIM
   mypy --strict   # graduel par module
   bandit -r app/
   ```

2. **Abandonner `main.py` racine + `api/routes.py` non auth + `storage.py` JSON**. Migrer le storage des analyses vers PostgreSQL (table `analyses`) — le stack a deja Postgres et asyncpg, c'est gratuit. Ajouter auth/rate-limit sur l'API d'analyse.

3. **Centraliser le pattern `_load_user_full`** dans `app/services/users.py` au lieu de le dupliquer dans 3 routes. Idem pour `_client_ip`, `_user_agent`, `_now` definis 4 fois.

4. **Boot-time validation des secrets** : ajouter `Settings.model_post_init` qui leve si `is_production and (secret_key.startswith("change_me") or postgres_password == "changeme" or not cron_secret or not resend_api_key)`.

5. **Tests d'integration** : `tests/test_integration.py`, `tests/test_auth_routes.py`, `tests/test_users_routes.py` existent — bien — mais aucun lance en CI visible. Verifier la couverture, surtout pour les flows CSRF/rate-limit.

6. **Migration des `selectinload("role")` strings → references typees** : ameliore la robustesse aux refactors et l'experience IDE.

7. **Documenter le flow d'authentification** dans un README backend dedie : cookies `cc_session` + `cc_csrf`, double-submit, idle expiry — non trivial pour un nouveau dev.

8. **Audit des emails non envoyes** : le pattern `try: send_xxx_email; except: pass` dans 4 endroits perd les emails sans trace. Mettre en place une outbox table (`pending_emails`) + worker async qui retry — pattern transactional outbox.
