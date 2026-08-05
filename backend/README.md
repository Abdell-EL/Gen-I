# Genius Services — Backend API

## Aperçu

Le backend **Genius Services** alimente la plateforme interne de gestion des connaissances métier de l'entreprise, fondée sur une architecture **RAG** (Retrieval-Augmented Generation). Il expose une API REST qui permet aux agents de rechercher et d'interroger la base documentaire, et fournit aux administrateurs les outils de gestion des utilisateurs, des contenus, des retours et des indicateurs opérationnels.

L'application frontend (React) communique exclusivement avec cette API ; les instructions frontend sont documentées séparément dans [`frontend/README.md`](frontend/README.md).

## Fonctionnalités actuelles

- Recherche sémantique et recherche par mots-clés
- Chat conversationnel généré localement, en mode streamé (NDJSON) et non streamé
- Sources citées automatiquement avec navigation vers les articles et téléchargement du document DOCX d'origine
- Métadonnées et enregistrements d'audit persistés dans PostgreSQL
- Indexation vectorielle Milvus pour la recherche sémantique
- Génération locale des réponses avec Ollama
- Limitation distribuée des tentatives d'authentification via Redis
- Authentification par JWT avec versionnement des identifiants (`token_version`) afin d’invalider les anciens jetons après activation, changement ou réinitialisation du mot de passe
- Contrôle d'accès par rôles (agents et administrateurs)
- Cycle d'invitation et d'activation de compte
- Cycle de changement et de réinitialisation de mot de passe
- Administration des utilisateurs (liste, création, modification, réinitialisation de mot de passe, relance d'invitation)
- Soumission de retours (feedback) et analyse des retours
- Analytique opérationnelle et intelligence de la connaissance
- Ingestion de documents DOCX
- Détection de doublons
- Mise à jour de documents avec versionnage
- Téléchargement du document original
- Supervision de la santé du système (health) et statistiques
- Intégration continue et scans de sécurité

## Architecture technique

```text
Frontend React ──> FastAPI API ──> PostgreSQL
                        │
                        ├──> Milvus (recherche vectorielle)
                        ├──> Redis (cache et limitation d'authentification)
                        └──> Ollama (génération locale)
```

- **PostgreSQL** : source de vérité pour les utilisateurs, documents, versions, chunks, audits, retours et analytique
- **Milvus** : index vectoriel dérivé pour la recherche sémantique
- **Redis** : cache borné et limitation distribuée des requêtes d'authentification
- **Ollama** : génération locale des réponses (modèles locaux, par exemple `llama3.2:3b`)

## Structure du projet

Les répertoires importants de `backend/` sont :

| Répertoire | Rôle |
| --- | --- |
| `app/` | Code de l'API FastAPI : routes, schémas, dépendances d'authentification, modèles et configuration |
| `app/services/` | Logique métier : recherche, chat, ingestion, versionnage, utilisateurs, invitations, mots de passe, analytique, santé système |
| `alembic/` | Migrations de schéma PostgreSQL (Alembic) |
| `data/` | Jeu de données pilote : articles DOCX source et fichiers de traitement (`chunks.json`, `embeddings.jsonl`, manifeste d'ingestion) |
| `docs/` | Documentation technique et opérationnelle (déploiement, runbooks, sécurité, limitations) |
| `frontend/` | Application React/Vite (référencée, voir la section Frontend) |
| `scripts/` | Scripts d'ingestion, d'embeddings, de chargement, de benchmark et d'administration |
| `tests/` | Tests backend (y compris les tests d'intégration PostgreSQL gardés) |
| `vector_db/` | Code et ressources liés à la base vectorielle |

Fichiers de configuration principaux :

- `Dockerfile` : image d'exécution de l'API (uvicorn)
- `requirements.txt` : dépendances Python de l'exécution (hors outils de développement)
- `alembic.ini` : configuration d'Alembic
- `docker-compose.yml` (racine du dépôt) : pile complète PostgreSQL, Milvus, Redis, Ollama et API

## Principaux groupes d'API

Toutes les routes sont préfixées par `/api/v1`. La spécification OpenAPI complète est disponible sur `/docs` et `/openapi.json`.

| Groupe | Routes représentatives |
| --- | --- |
| Santé et statistiques | `GET /health`, `GET /stats` |
| Authentification | `POST /auth/signin`, `GET /auth/me`, `POST /auth/activation/*`, `POST /auth/password/forgot`, `POST /auth/password/reset/*`, `POST /auth/password/change` |
| Administration des utilisateurs | `GET/POST /admin/users`, `PATCH /admin/users/{user_id}`, `POST /admin/users/{user_id}/resend-invitation`, `POST /admin/users/{user_id}/reset-password` |
| Recherche et chat | `POST /search`, `POST /keyword-search`, `POST /chat`, `POST /chat/stream` |
| Sources et téléchargement | `GET /knowledge/articles/{source_document_id}`, `GET /knowledge/documents/{source_document_id}/original` |
| Retours (feedback) | `POST/GET/DELETE /chat/messages/{message_id}/feedback`, `GET /admin/analytics/feedback*` |
| Analytique | `GET /admin/analytics/users`, `GET /admin/analytics/questions`, `GET /admin/analytics/operations/*`, `GET /admin/analytics/knowledge/*` |
| Ingestion et versionnage | `POST /admin/ingestion/docx`, `GET /admin/ingestion/jobs*`, `POST/GET /admin/knowledge/documents/{source_document_id}/versions` |
| Récupération des audits | `GET /audit/retrievals/latest`, `GET /audit/retrievals/{retrieval_id}` |

## Démarrage local

La méthode recommandée pour exécuter le backend et ses dépendances est **Docker Compose** depuis la racine du dépôt. La pile comprend PostgreSQL, Milvus (avec etcd et MinIO), Redis, Ollama et l'API.

Prérequis :

- Docker Engine et Docker Compose v2
- Un fichier `.env` à la racine, basé sur `backend/.env.example` et la documentation de déploiement

```bash
docker compose up -d
```

## Commandes utiles

```bash
# Démarre l'ensemble des services (API, PostgreSQL, Milvus, Redis, Ollama)
docker compose up -d

# Liste l'état des conteneurs
docker compose ps

# Affiche les 100 dernières lignes de logs de l'API
docker compose logs --tail=100 api

# Vérifie la santé de l'API
curl http://127.0.0.1:8000/api/v1/health
```

La documentation interactive de l'API est disponible sur `http://127.0.0.1:8000/docs`.

## Frontend

Le frontend est une application React/Vite située dans `backend/frontend/`. Toutes les instructions d'installation, de développement et de validation frontend sont documentées dans [`frontend/README.md`](frontend/README.md) et ne sont pas dupliquées ici.

## Tests et validation

La validation du backend s'appuie sur plusieurs niveaux :

- Tests backend : suite `unittest` sous `backend/tests`, exécutée par le workflow CI `backend-quality` (compilation, découverte des tests, inventaire des routes OpenAPI, vérification de la chaîne de migrations Alembic)
- Tests frontend : `npm test` exécuté par le workflow CI `frontend-quality`
- Lint et build frontend : `npm run lint` et `npm run build`
- Qualité conteneur : construction de l'image Docker et validation `docker compose config --quiet`
- Sécurité : scans de dépendances (`pip-audit`, `npm audit`), recherche de secrets (Gitleaks) et scans image/système de fichiers (Trivy)

La suite backend repose principalement sur `unittest` et s’exécute dans l’environnement CI, en dehors du conteneur de production. L’image d’exécution contient uniquement les dépendances nécessaires au fonctionnement de l’API ; les outils de développement supplémentaires, notamment `pytest`, n’y sont volontairement pas installés afin de réduire sa surface et son empreinte.

Le workflow CI et les contrôles de sécurité sont détaillés dans [`docs/ci.md`](docs/ci.md).

## Configuration

La configuration opérationnelle se fait principalement par variables d’environnement. Certains paramètres de développement, notamment les origines CORS locales, disposent encore de valeurs déclarées dans `app/main.py`.
(voir `backend/.env.example` et la documentation de déploiement). Les variables sont regroupées par catégorie :

| Catégorie | Variables (exemples) |
| --- | --- |
| Base de données PostgreSQL | `DATABASE_URL`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_HOST`, `POSTGRES_PORT`, `POSTGRES_DB` |
| Milvus | `MILVUS_HOST`, `MILVUS_PORT`, `MILVUS_COLLECTION` |
| Redis et cache | `REDIS_URL`, `CACHE_ENABLED`, `CACHE_NAMESPACE`, `CACHE_*_TTL_SECONDS` |
| Ollama | `OLLAMA_URL`, `OLLAMA_MODEL`, `OLLAMA_FAST_MODEL`, `OLLAMA_NUM_CTX`, `OLLAMA_NUM_PREDICT`, `OLLAMA_TEMPERATURE`, `OLLAMA_REQUEST_TIMEOUT_SECONDS` |
| JWT | `AUTH_JWT_SECRET`, `AUTH_JWT_ISSUER`, `AUTH_JWT_AUDIENCE`, `AUTH_ACCESS_TOKEN_MINUTES` |
| CORS | Origins autorisées déclarées dans `app/main.py` (développement local) |
| Email et invitations | `FRONTEND_ACTIVATION_URL`, `INVITATION_EMAIL_PROVIDER`, `INVITATION_TOKEN_LIFETIME_MINUTES`, `INVITATION_RESEND_COOLDOWN_SECONDS`, `FRONTEND_PASSWORD_RESET_URL`, `PASSWORD_RESET_EMAIL_PROVIDER`, `PASSWORD_RESET_TOKEN_TTL_MINUTES` |
| Limitation d'authentification | `AUTH_RATE_LIMIT_ENABLED`, `AUTH_RATE_LIMIT_REDIS_URL`, `AUTH_RATE_LIMIT_HMAC_SECRET`, politiques `AUTH_RATE_LIMIT_*` |

> Les valeurs de secrets ne doivent jamais être versionnées dans le dépôt. Utiliser le fichier `.env` local et les secrets de l'environnement GitHub pour la production.

## Documentation opérationnelle

- [Déploiement](docs/deployment.md)
- [Checklist de déploiement](docs/deployment-checklist.md)
- [Runbook d'exploitation](docs/operations-runbook.md)
- [Sauvegarde et restauration](docs/backup-restore-runbook.md)
- [Durcissement de la sécurité](docs/security-hardening.md)
- [Limitations connues et feuille de route](docs/known-limitations.md)
- [Passation production](docs/production-handoff.md)

## État validé actuel

Le jeu de données pilote actuellement déployé présente les chiffres suivants :

- **2 345 chunks** dans PostgreSQL
- **30 documents source** (articles DOCX)
- **2 345 vecteurs** dans Milvus
- **Domaine de connaissance pilote** : FDE

Ces chiffres reflètent le jeu de données pilote actuellement déployé (dérivé de `backend/data/processed/`) et ne constituent pas des limites dures de la plateforme. La base de connaissances est conçue pour évoluer et être étendue à d'autres périmètres métier.

## Limitations connues

Les limitations connues, leur impact, les responsables et les actions recommandées sont détaillés dans [`docs/known-limitations.md`](docs/known-limitations.md). Ce document ne duplique pas la liste complète ; les points notables concernent notamment l'authentification d'entreprise (Entra ID), la délivrance d'emails en production, la haute disponibilité et la validation de charge.

## Projet interne

Genius Services a été développé comme plateforme interne de gestion des connaissances métier de l'entreprise, dans le cadre d'un stage. Les documents, données, identifiants et configurations de production ne doivent pas être publiés ou stockés dans le dépôt.