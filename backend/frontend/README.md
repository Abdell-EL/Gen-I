# Genius Services — Frontend

## Vue d'ensemble

Le frontend **Genius Services** est le client web React/TypeScript de la plateforme interne de connaissance d'entreprise. Il permet aux agents et aux administrateurs d'interroger la base documentaire, d'obtenir des réponses sourcées et traçables, de télécharger les documents d'origine et de piloter l'administration de la plateforme depuis une interface unique, sécurisée et responsive.

Le domaine de connaissance actuellement pilote est le domaine **FDE**. L’application est une single-page application (SPA) construite avec Vite., qui communique exclusivement avec l'API FastAPI du backend via l'URL de base configurée par `VITE_API_BASE_URL`.

## Espaces utilisateurs principaux

### Page d'accueil publique

- **Landing page** (`/`) — `LandingPage` : présentation de la plateforme Genius Services, navigation publique et accès à la connexion.

### Pages d'authentification

- **Connexion** (`/signin`) — `SignInPage` : authentification par email et mot de passe auprès du backend.
- **Activation d'invitation** (`/activate`) — `ActivationPage` : activation d'un compte invité à partir d'un lien d'invitation à usage unique, retiré de l'historique du navigateur.

### Console Agent

- **Espace Agent** (`/agent`) — `AgentPage` : assistant de connaissance avec chat, réponses générées en streaming, sources citées et téléchargement du document original.

### Console Administrateur

- **Espace Administrateur** (`/admin`) — `AdminPage` : tableau de bord d'administration avec vue d'ensemble, santé système, statistiques, audits de récupération, gestion des utilisateurs, analyse d'activité et des questions, intelligence documentaire, feedback et mise à jour de la base documentaire.

### Aperçu d'article

- **Page article** (`/articles/:sourceDocumentId`) — `ArticlePage` : consultation authentifiée d'un article de la base documentaire, avec surlignage du passage cité et indication de version.

### Pages du cycle de vie du mot de passe

- **Changement de mot de passe** (`/settings/password`) — `ChangePasswordPage` : modification du mot de passe courant ; la réussite force une reconnexion.
- **Mot de passe oublié** (`/forgot-password`) — `ForgotPasswordPage` : demande de réinitialisation par email (flux neutre, sans révélation d'état).
- **Réinitialisation** (`/reset-password`) — `ResetPasswordPage` : validation du lien de réinitialisation et définition d'un nouveau mot de passe.

## Capacités actuelles

- **Authentification JWT via l'API backend** : connexion (`POST /auth/signin`), restauration de session (`GET /auth/me`) et jeton Bearer stocké dans le `sessionStorage` uniquement.
- **Activation d'invitation** : validation du jeton d'activation et finalisation du compte avec définition du mot de passe.
- **Connexion** : formulaire sécurisé avec gestion des erreurs et des états de soumission.
- **Changement de mot de passe** : vérification du mot de passe courant et reconnexion obligatoire après succès.
- **Demande / validation / finalisation de réinitialisation de mot de passe** : cycle complet de réinitialisation par lien à usage unique.
- **Routage par rôle** : les routes protégées sont conditionnées par le rôle (`agent`, `admin`) via `ProtectedRoute` ; le backend reste l'autorité d'autorisation.
- **Chat agent** : envoi d'une question et affichage de la réponse en streaming.
- **Réponses en streaming** : lecture du flux NDJSON (`POST /chat/stream`) avec gestion des coupures, des événements partiels et de l'annulation.
- **Citations des sources** : liste des sources avec score, référence documentaire et lien vers l'aperçu.
- **Téléchargement du document original DOCX** : récupération en `Blob` et téléchargement avec un nom de fichier assaini.
- **Contrôles de feedback** : évaluation des réponses (utile, partiellement utile, inutile), avec raison et commentaire, modification et suppression.
- **Tableau de bord analytique administrateur** : indicateurs d'usage, questions fréquentes, santé et statistiques.
- **Gestion des utilisateurs** : création, invitation, renvoi d'invitation, modification, désactivation et réinitialisation de mot de passe par un administrateur.
- **Intelligence documentaire** : analyse des questions tendances, de la confiance, de la distribution des scores et du contenu non référencé.
- **Ingestion et mises à jour de version** : téléversement de DOCX et publication de nouvelles versions avec historique.
- **Vues santé, audits et statistiques** : état du système, santé système, statistiques et journaux de récupération documentaire et indicateurs documentaires.
- **Identité visuelle Genius Services** : nom de produit et marque appliqués sur l'ensemble des espaces.
- **Mises en page responsives** : adaptation des consoles et de la navigation aux écrans réduits.
- **États de chargement, vides et d'erreur** : composants dédiés (`LoadingState`, `EmptyState`, `ErrorState`) sur les espaces agent et administrateur.

## Pile technique

- **React** — bibliothèque d'interface (SPA).
- **TypeScript** — typage statique du code applicatif.
- **Vite** — serveur de développement et build de production (`tsc -b && vite build`).
- **React Router** — routage côté client (`react-router-dom`).
- **Lucide React** — icônes de l'interface.
- **Système de design CSS** — design system défini dans `src/styles/global.css` (variables de marque, thème clair, mises en page responsives).
- **Clients HTTP** — wrapper axios centralisé (src/services/apiClient.ts) pour les appels REST, et client fetch natif (src/services/chatStream.ts) pour le streaming NDJSON.- **Node test runner** — exécution des tests avec `node --test` (`node:test`).

## Structure du projet

```
src/
├── app/          # Routage, contexte d'authentification, gardes de route
├── components/   # Layout (sidebars, shells, navigation publique) et composants UI réutilisables
├── features/     # Logique métier par domaine (admin, auth, chat)
├── pages/        # Pages de l'application (landing, auth, agent, admin, article, etc.)
├── services/     # Clients API (auth, chat, streaming, admin, documents, mots de passe, feedback)
├── styles/       # Design system CSS global
└── types/        # Types TypeScript (backend, auth, admin)

tests/            # Tests du frontend (node --test tests/*.test.ts)
```

- `src/app` — `AppRouter`, `AuthContext`, `AuthProvider`, `ProtectedRoute`, `useAuth`.
- `src/components` — `layout/` (sidebars, `DashboardShell`, `PublicNav`, `BrandLockup`, `AuthLayout`) et `ui/` (boutons, cartes, badges, états de chargement/vide/erreur).
- `src/features` — `admin/` (analytique, utilisateurs, intelligence documentaire, feedback, mises à jour), `auth/` (flux d'activation et de réinitialisation), `chat/` (panneau de réponse, sources, éditeur de question, navigation vers les articles).
- `src/pages` — `LandingPage`, `SignInPage`, `ActivationPage`, `AgentPage`, `ArticlePage`, `ChangePasswordPage`, `ForgotPasswordPage`, `ResetPasswordPage`, `AdminPage`, `NotFoundPage`.
- `src/services` — clients API et logique de transport (`apiClient`, `authApi`, `activationApi`, `chatApi`, `chatStream`, `feedbackApi`, `knowledgeArticleApi`, `knowledgeDocumentApi`, `passwordLifecycleApi`, `authStorage`, `adminApi`).
- `src/styles` — `global.css` : variables de marque, thème, composants et points de rupture responsives.
- `src/types` — définitions partagées avec le backend et l'administration.
- `tests` — suite de tests exécutée par le runner Node.

## Routage

Routage déclaré dans `src/app/AppRouter.tsx` :

| Type de route | Chemins | Accès |
| --- | --- | --- |
| Publiques | `/`, `/signin`, `/activate`, `/forgot-password`, `/reset-password` | Accès libre |
| Protégées | `/agent`, `/articles/:sourceDocumentId`, `/settings/password` | Rôles `agent` et `admin` |
| Réservée aux administrateurs | `/admin` | Rôle `admin` uniquement |
| Repli | `*` → `NotFoundPage` | — |

Le garde `ProtectedRoute` améliore la navigation selon le rôle de l'utilisateur ; l'autorisation effective est appliquée par le backend.

## Intégration backend

- **VITE_API_BASE_URL** — URL de base de l’API backend, lue par `src/services/apiClient.ts`. En l’absence de fichier d’environnement frontend versionné, elle peut être fournie dans un fichier local `.env` non versionné ou directement lors du build. Valeur par défaut : `http://127.0.0.1:8000/api/v1`.
- **`VITE_AUTH_MODE`** — variable de build validée par l'outillage de déploiement (`scripts/deploy_vm.sh`, `.github/workflows/deploy-vm.yml`) et passée à `npm run build` ; le déploiement de production exige la valeur exacte `backend`.
- **Flux d'authentification API** — la connexion envoie les identifiants à `POST /auth/signin` ; le jeton JWT reçu est conservé en `sessionStorage` ; un interceptor `axios` ajoute l'en-tête `Authorization: Bearer` à chaque appel ; `GET /auth/me` restaure la session au chargement ; la déconnexion vide la session et redirige vers `/signin`.
- **Client de streaming du chat** — `POST /chat/stream` via `fetch` natif avec `Accept: application/x-ndjson` ; le corps de la réponse est lu en flux, décodé en UTF-8 et découpé en événements typés (métadonnées, jetons, fin, erreur) ; un repli sur `POST /chat` est prévu si le streaming n'est pas disponible.
- **Endpoints sources et documents** — `GET /knowledge/articles/{sourceDocumentId}` (aperçu d'article, avec `version_id` et `chunk_id`) et `GET /knowledge/documents/{sourceDocumentId}/original` (téléchargement du DOCX original en `Blob`).
- **Clients API administrateur** — santé (`/health`), statistiques (`/stats`), audits (`/audit/retrievals`), ingestion (`/admin/ingestion/docx`, jobs), versions documentaires (`/admin/knowledge/documents/{id}/versions`), utilisateurs (`/admin/users`) et analytiques (`/admin/analytics/*`).
- **Recommandation de production même origine** — servir le build statique et le chemin `/api/v1` sur la même origine pour éviter les problématiques de CORS et simplifier la configuration.

## Développement local

```bash
npm ci
npm run dev
npm test
npm run lint
npm run build
```

`npm ci` installe les dépendances de manière reproductible depuis `package-lock.json`. `npm run dev` démarre le serveur de développement Vite. `npm test` exécute la suite de tests. `npm run lint` vérifie le code avec ESLint. `npm run build` produit le build de production dans `dist/`.

## Variables d'environnement

Variables présentes dans le dépôt :

- `VITE_API_BASE_URL` — URL de base de l'API backend, lue par `src/services/apiClient.ts` ; définie dans `.env.example` ; défaut : `http://127.0.0.1:8000/api/v1`.
- `VITE_AUTH_MODE` — variable de build utilisée par l'outillage de déploiement de production ; la valeur `backend` est requise pour tout déploiement de production (script de déploiement bloquant sinon).

Aucun secret ne doit être placé dans les variables d'environnement du frontend : elles sont embarquées dans les assets statiques et visibles par le navigateur.

## Tests

La suite de tests est exécutée avec :

```bash
npm test
```

soit `node --test tests/*.test.ts` avec le runner intégré de Node.

- **Tests de contrats frontend** — vérifient les formes de requêtes attendues par le backend (cycle de vie du mot de passe, mises à jour de version, téléchargement de document, feedback).
- **Tests du cycle de vie d'authentification** — activation d'invitation, connexion, changement de mot de passe, demande/validation/finalisation de réinitialisation, et retrait des jetons de l'historique du navigateur.
- **Tests de streaming du chat** — analyse NDJSON, découpage UTF-8, annulation, expirations de session et réponses partielles.
- **Tests d'analytique** — mise en forme des indicateurs administrateur et des vues d'intelligence documentaire.
- **Tests de navigation et téléchargement des sources** — construction des chemins d'article et téléchargement du document original dans `src/services/knowledgeDocumentApi.ts`.
- **Lint et build de production** — `npm run lint` (ESLint) et `npm run build` (compilation TypeScript + build Vite) servent de contrôles de qualité.

## Système de design et marque

- **Marque Genius Services basée sur la typographie** — nom de produit « Genius Services » comme identité visuelle principale, typographie de corps Calibri / « Segoe UI » / Arial et typographie d'affichage Playfair Display pour les titres.
- **Palette SOGETREL2025** — bleu marine `#214E88`, or `#D8AF76`, bleu doux `#A9BBCC`, accent chaud de tableau `#DAC7A9`, violet profond `#3E3547`, texte `#4A4B63`, danger `#BF0000` et succès `#168980`.
- **Comportement responsive des barres latérales** — sur grand écran, les barres latérales agent et administrateur sont verticales et sticky ; sous 900 px, elles deviennent une barre horizontale sticky en haut de l'écran.
- **Tableau de bord administrateur inspiré de la BI d'entreprise** — panneaux analytiques, grilles d'indicateurs et graphiques présentés dans un style décisionnel d'entreprise.
- **Pas de mode sombre actif** — le thème est défini en clair uniquement ; `prefers-reduced-motion` est respecté.

## Build de production

- `dist/` est généré par Vite via `npm run build` (`tsc -b && vite build`).
- `dist/` ne doit jamais être édité manuellement : chaque build est produit de manière reproductible depuis le code source.
- Les assets sont nommés avec des empreintes (hashes) par Vite pour faciliter la mise en cache et l'invalidation.
- Le service de production est géré séparément par Nginx ou un hébergement statique ; voir `../docs/deployment.md`.

## Notes de production

- Recommandation d'une architecture même origine : servir le build statique et router `/api/v1` vers l'API sur la même origine.
- Le build de production doit utiliser `VITE_API_BASE_URL=/api/v1` pour une intégration même origine.
- Les instructions de service en production sont détaillées dans `../docs/deployment.md` et `../docs/production-handoff.md`.
- Ne jamais exposer de secrets dans les variables d'environnement du frontend (visibles par le navigateur).

## Limitations connues

Voir `../docs/known-limitations.md` pour la liste complète.

Limitations relatives au frontend actuel :

- La fédération d'identité de production n'est pas encore implémentée (aucune intégration Entra ID / SSO).
- L'observabilité globale et la validation sous charge à grande échelle restent des travaux externes.
- Le mode sombre n'est pas implémenté.
- Certaines fonctions avancées de reporting/export restent des évolutions à venir.

## Mention de projet interne

Ce frontend est un développement interne réalisé dans le cadre d'un stage, destiné à l'accès à la connaissance d'entreprise pour la plateforme Genius Services.