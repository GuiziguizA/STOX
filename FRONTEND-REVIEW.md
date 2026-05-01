# Review Frontend — Projet Action

> Review effectuee par l'agent `typescript-reviewer` (ECC v2.0.0-rc.1) le 2026-05-01.
> Cible : `frontend/` (clone `GuiziguizA/projet-action-frontend`).
> Stack : Next.js 16 App Router / React 19 / TypeScript 5 strict / Tailwind 4 / react-hook-form + zod / recharts.

## Resume

- **Verdict** : **Block** — la zone authentifiee est soit inaccessible soit dangereuse, refuse merge tant que les CRITICAL ne sont pas fixes
- **Fichiers analyses** : 36 fichiers source (`app/`, `components/`, `lib/`, `hooks/`, `types/`) + config
- **Findings** : **4 CRITICAL · 9 HIGH · 8 MEDIUM**
- **Outils** : `tsc` OK (0 erreur) · `eslint` failed (42 erreurs / 8 warnings)

---

## Ce qui va bien

- **`tsconfig.json` strict mode actif** (`"strict": true`) et `tsc` propre — discipline reelle sur les types
- **`lib/api-client.ts`** centralise fetch + CSRF + parsing erreur typee `ApiClientError` — design propre, reutilisable
- **Validation zod systematique** sur tous les forms (`login`, `register`, `reset-password`, `forgot-password`, `invite`, `profile`, `security`, `admin/users/[id]`)
- **Anti-enumeration** sur `app/(public)/forgot-password/page.tsx:38-40` — message generique "Si cet email existe..."
- **`lib/ratelimit.ts`** : pattern Upstash optionnel propre, degradation gracieuse en dev (`return null` si pas configure)
- **Aucun `console.log`, `eval`, `dangerouslySetInnerHTML`, `throw "string"`** dans tout le repo
- **`.env.local` correctement ignore** par `.gitignore` (`.env*`)
- **Types API** (`types/api.ts`, `types/analysis.ts`) bien definis cote frontend, alignes sur le backend

---

## CRITICAL (a fixer avant deploy)

### Middleware d'auth completement non-fonctionnel
- **File** : `proxy.ts:25,52`
- **Issue** : Le fichier s'appelle `proxy.ts` et exporte `proxy()`. Next.js 16 attend `middleware.ts` a la racine avec un export `middleware()`. Aucun fichier `middleware.ts` n'existe dans le repo. Resultat : **toutes les routes `(protected)` et `(admin)` sont accessibles sans authentification** ni verification de permission. Les layouts `(protected)/layout.tsx` et `(admin)/layout.tsx` ne contiennent aucun garde server-side — ils sont purement visuels (`'use client'`, lecture de `useSession()` qui peut etre null sans bloquer le rendu).
- **Fix** : Renommer en `middleware.ts`, exporter `middleware` (pas `proxy`), confirmer que `config.matcher` couvre bien `/dashboard`, `/settings`, `/admin`. Verifier aussi que `if (!isProtected) return NextResponse.next()` est atteinte sur les pages publiques (le matcher actuel attrape tout ce qui n'est pas `_next/static`, donc aussi `/login`).

### Route admin sans aucun garde + UI fait fuiter le menu admin a tout utilisateur connecte
- **Files** : `app/(admin)/layout.tsx:14-79`, `app/(protected)/layout.tsx:18-19`
- **Issue** : `AdminLayout` ne verifie pas `user?.permissions` avant de render — n'importe quel utilisateur authentifie atteignant `/admin/users` voit toute la page (les requetes API echoueront cote backend, mais l'UI s'affiche, charge des inputs admin, et confirme aux attaquants l'existence de la route + structure). Combine avec le middleware non-fonctionnel ci-dessus, c'est une faille d'autorisation. La verification `canAccessAdmin` dans `(protected)/layout.tsx:18-19` ne sert qu'a afficher le lien.
- **Fix** : Dans `(admin)/layout.tsx`, verifier `user?.permissions` cote client (redirect immediat si manquant) **et** rendre le layout `async` server-component avec lecture cookies + appel `/auth/me` server-side, ou s'appuyer sur le middleware corrige.

### URL double-prefixee — l'export RGPD et la suppression de compte sont casses
- **File** : `app/(protected)/settings/account/page.tsx:11,32,62`
- **Issue** : Ligne 11 `const API_BASE = (process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000') + '/api/v1'`. Lignes 32 et 62 appellent ensuite `${API_BASE}/api/v1/users/me/export` et `${API_BASE}/api/v1/users/me/delete-account` — ce qui produit `http://localhost:8000/api/v1/api/v1/users/me/...` (404 systematique). **Bug fonctionnel direct sur deux droits RGPD obligatoires** (export, suppression).
- **Fix** : Remplacer par `${API_BASE}/users/me/export` et `${API_BASE}/users/me/delete-account`, ou mieux : utiliser `api.get`/`api.post` du client (qui calque deja la logique CSRF et le base path). Le code re-implemente `getCsrfToken()` (lignes 13-17) en doublon de `lib/api-client.ts:15-19`.

### Changement de mot de passe via un endpoint reset avec un token bidon
- **File** : `app/(protected)/settings/security/page.tsx:48-54`
- **Issue** : `onChangePassword` appelle `POST /auth/reset-password` avec `token: '__change_password__'` — un token magique cote frontend pour reuser l'endpoint de reset. Soit le backend accepte cette chaine (**faille d'authentification : changement de password sans verification du mot de passe actuel ni token de reset valide**), soit l'appel echoue toujours (feature cassee). Dans les deux cas c'est bloquant. Aucun champ "ancien mot de passe" n'est demande dans le form — aucun re-auth.
- **Fix** : Implementer un vrai endpoint cote backend `PATCH /users/me/password` exigeant `current_password` + `new_password`, et appeler ce endpoint depuis le form. Ne jamais hardcoder de token cote client.

---

## HIGH (a planifier)

### Aucune ErrorBoundary / route `error.tsx` / `loading.tsx`
- **File** : `app/**` (aucun fichier `error.tsx`, `loading.tsx` ou `not-found.tsx` trouve dans `app/`)
- **Issue** : Une erreur dans n'importe quel client component (`AnalysisDashboard`, `AdminUserDetailPage` etc.) crashe l'arbre React jusqu'au layout root. Pas de feedback utilisateur, pas d'isolation par segment.
- **Fix** : Ajouter au minimum `app/error.tsx`, `app/loading.tsx`, et un par groupe sensible (`app/(admin)/error.tsx`, `app/(protected)/error.tsx`).

### Pseudo-loading infini en cas de 401 sur `/auth/me`
- **File** : `lib/session-context.tsx:24-31`
- **Issue** : Si `api.get('/auth/me')` echoue avec un statut autre que 401 (500, network), le `catch` ne logge rien, ne set ni `user` ni `error`. Le `finally` met bien `loading` a `false`, mais sans erreur exposee, l'utilisateur ne sait pas pourquoi rien ne s'affiche.
- **Fix** : Distinguer les deux cas (401 = anonyme, autre = erreur reseau a remonter), exposer un `error` dans le contexte, `console.error` minimum.

### Promesse non geree sur charge de roles dans page admin user
- **File** : `app/(admin)/admin/users/[id]/page.tsx:68`
- **Issue** : `api.get<RoleOut[]>('/roles').then(setAllRoles).catch(() => {})` — le catch vide swallow toute erreur (perte de feedback). Si `/roles` echoue, l'UI affiche eternellement "Chargement des rôles…" (ligne 206) sans message d'erreur, et le bouton "Appliquer les rôles" reste invisible.
- **Fix** : Setter une erreur dans le state, afficher un message ou un bouton "reessayer".

### `proxy.ts` : `isPublicAuth` calcule mais jamais utilise (bug logique)
- **File** : `proxy.ts:30`
- **Issue** : La variable est calculee mais jamais lue — l'intention etait probablement de rediriger les utilisateurs deja connectes hors de `/login`, `/register` etc. Detecte par eslint (`no-unused-vars`).
- **Fix** : Soit implementer la logique manquante (`if (isPublicAuth && ok) return NextResponse.redirect(new URL('/dashboard', request.url))`), soit supprimer.

### Type-cast contournant la verification zod
- **File** : `lib/ratelimit.ts:21`
- **Issue** : `Ratelimit.slidingWindow(requests, window as Parameters<typeof Ratelimit.slidingWindow>[1])` — cast `as` qui bypass la verification du format string. Si quelqu'un appelle `makeRatelimit(5, 'invalid')`, ca compile.
- **Fix** : Restreindre le type de `window` a `` `${number} ${'s' | 'm' | 'h' | 'd'}` `` (template literal type) au lieu de `string`.

### Non-null assertion sans guard
- **File** : `app/(protected)/settings/profile/page.tsx:62`
- **Issue** : `await api.patch(\`/users/${user!.id}\`, ...)` — `user` peut etre null. Le `useEffect` ligne 47 protege le reset, mais `onSubmit` est theoriquement appelable avant que user soit charge si l'utilisateur soumet vite.
- **Fix** : `if (!user) return; await api.patch(\`/users/${user.id}\`, ...)`.

### `JSON.parse` sans logging dans EventSource handler — `catch` vide
- **File** : `lib/api.ts:18-34`
- **Issue** : Le `try` enveloppe le `JSON.parse`, mais le `catch` est completement vide ("ignore parse errors"). Aucun timeout reseau individuel — un `EventSource.onerror` peut renvoyer des erreurs en boucle silencieuse.
- **Fix** : Au minimum logger les parse errors. Idealement valider via zod le shape du `ProgressEvent`.

### Empty interface (eslint `no-empty-object-type`)
- **File** : `components/ui/ButtonText.tsx:3`
- **Issue** : `interface ButtonTextProps extends React.ButtonHTMLAttributes<HTMLButtonElement> {}`.
- **Fix** : `type ButtonTextProps = React.ButtonHTMLAttributes<HTMLButtonElement>`.

### Re-implementation de `getCsrfToken` en parallele du client centralise
- **File** : `app/(protected)/settings/account/page.tsx:13-17`
- **Issue** : Duplique exactement `lib/api-client.ts:15-19`. Si le nom de cookie change (cf. commit recent `cc_csrf`), il faudra updater deux endroits — risque de divergence.
- **Fix** : Exporter `getCsrfToken` depuis `lib/api-client.ts`, ou mieux : passer par `api.post()` au lieu d'un fetch raw.

---

## MEDIUM (nice to have)

### `react-hooks/set-state-in-effect` (8 occurrences)
- **Files** : `lib/session-context.tsx:42`, `app/(admin)/admin/users/[id]/page.tsx:67`, `app/(admin)/admin/users/page.tsx:47`, `app/(public)/verify-email/page.tsx:18`, `components/AnalysesTable.tsx:150`, `components/SearchBar.tsx:34`, `components/ui/CookieBanner.tsx:13`, `components/ui/OnboardingModal.tsx:40`
- **Issue** : Pattern flague par les nouvelles regles eslint-config-next. Regle React 19 : preferer `use()` ou stocker la valeur en derive direct au render.
- **Fix** : Pour les loaders async (`AnalysesTable`), c'est legitime mais prefer `use()` ou TanStack Query. Pour `OnboardingModal:36-41`, lire `localStorage` synchrone dans le init du `useState` (`useState(() => ...)`).

### `key={index}` dans listes
- **Files** : `components/LoadingSkeleton.tsx:32,47,58`, `components/AnalysesTable.tsx:179`, `components/ScoreBreakdown.tsx:261,461,474`, `components/ui/OnboardingModal.tsx:71`, `components/ui/PasswordStrength.tsx:56`
- **Issue** : Pour skeletons et listes statiques c'est acceptable. Pour `AnalysesTable.tsx:229` `key={\`${entry.ticker}-${i}\`}`, le ticker devrait suffire en cle (les analyses sont dedupliquees par ticker cote backend ?).
- **Fix** : Verifier l'unicite cote `getAnalyses()` et utiliser `entry.ticker` seul, ou un id back-end stable.

### Magic number et latency arbitraire
- **File** : `app/page.tsx:31`
- **Issue** : `setTimeout(() => analyze(ticker), 50)` — 50ms magic, sans commentaire (probablement laisser le `reset()` flusher React state). Fragile.
- **Fix** : Utiliser `flushSync` de react-dom pour forcer le flush, ou refactor pour ne pas avoir besoin du timeout.

### `any` dans tooltips recharts
- **Files** : `components/RevenueChart.tsx:33`, `components/RevenueHistoryChart.tsx:52`
- **Issue** : `payload?: readonly any[]` avec eslint-disable. Typique de recharts qui n'expose pas un type publique correct, mais le narrowing `payload[0]?.value` est fragile.
- **Fix** : Definir un mini-type `{ value: number }[]` au lieu de `any[]`.

### `next.config.ts` rewrites contradictoires avec `api-client.ts`
- **Files** : `next.config.ts:8-16`, `lib/api-client.ts:3`
- **Issue** : Les rewrites mappent `/api/analyze/:path*` → `${API_BASE}/analyze/:path*`, mais `lib/api-client.ts` fetch directement `${API_BASE}/api/v1${path}` (cross-origin direct). Les rewrites ne sont pas utilises par le code auth/users (ce qui demande CORS configure cote backend) et le commentaire FIN-62 du dernier commit ("préfixe /api/v1 manquant") confirme l'incoherence.
- **Fix** : Decider une strategie : soit tout passer par les rewrites (proxy via Next, pas de CORS) — alors `api-client.ts` doit appeler `/api/v1${path}` (relatif). Soit assumer le cross-origin direct et supprimer les rewrites obsoletes.

### Pas de headers de securite
- **File** : `next.config.ts` (absence)
- **Issue** : Aucun `headers()` dans la config — pas de CSP, X-Frame-Options, HSTS, X-Content-Type-Options, Referrer-Policy.
- **Fix** : Ajouter un bloc `async headers()` pour au minimum `Strict-Transport-Security`, `X-Content-Type-Options: nosniff`, `Referrer-Policy: strict-origin-when-cross-origin`. CSP necessite plus d'attention (Tailwind injecte du style inline).

### Code mort : `lib/email.ts` (resend) et `lib/audit.ts` (Supabase)
- **Files** : `lib/email.ts`, `lib/audit.ts`
- **Issue** : Aucun import depuis `app/`. `RESEND_API_KEY` est lu au top-level mais le module n'est jamais utilise. Sans doute des reliquats du fork Supabase pre-migration FastAPI.
- **Fix** : Supprimer si vraiment dead, ou documenter qu'ils sont reserves a une future API route.

### `react/no-unescaped-entities` (~30 occurrences)
- **Files** : surtout `app/(public)/legal/{terms,privacy,cookies}/page.tsx`, plus `app/(protected)/settings/account/page.tsx`, `components/ui/CookieBanner.tsx:42`, `components/ScoreBreakdown.tsx:375`
- **Issue** : Apostrophes francaises non echappees (`l'application` au lieu de `l&apos;application`). Bloque le build par defaut sous eslint-config-next.
- **Fix** : Soit echapper les apostrophes (`&apos;`), soit configurer la regle off pour `legal/**` (textes longs).

---

## Recommandations transverses

1. **Bloquant pour deploy** : middleware non-fonctionnel + URLs cassees `/api/v1/api/v1/...` + password change avec token magique = la zone authentifiee est en l'etat soit inaccessible soit dangereuse. **A traiter en priorite avant tout merge.**

2. **Strategie API a clarifier** : choisir entre rewrite Next.js (mono-origin) et CORS direct, et nettoyer la duplication `next.config.ts` rewrites vs `api-client.ts`. Le double `getCsrfToken` montre le besoin d'un seul module HTTP.

3. **Rate limiting non branche** : `lib/ratelimit.ts` est defini (`loginRatelimit`, `signupRatelimit`, `resetRatelimit`) mais aucun appel dans `app/` (pas de route handler Next). Si le backend FastAPI ne fait pas de rate-limit, c'est un risque (brute-force login). Le backend FAIT du rate-limit (cf review backend) — donc ratelimit.ts cote frontend est juste mort.

4. **Server Components inexploites** : tout est `'use client'`, y compris des pages purement statiques (legal, dashboard cards). Migrer ces pages en Server Components ameliorerait perf (pas d'hydratation) et bundle size.

5. **Tests manquants** : aucun fichier `.test.ts(x)` ou config Jest/Vitest. Pas de testing setup pour valider les flows critiques (login, password reset, admin user update).

6. **Erreurs catch → message generique** : beaucoup de catches finissent par "Erreur inattendue" sans capture (pas de Sentry, pas de log). Pour un MVP V4 c'est acceptable, mais a tracker.

7. **Migration Next.js 16 inachevee** : `AGENTS.md` rappelle "This is NOT the Next.js you know", la structure App Router est utilisee, mais l'absence de Server Components et de middleware fonctionnel suggere que la migration n'est pas terminee.
