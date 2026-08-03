# Plateforme de Gestion des Connaissances Sogetrel 

Plateforme interne basée sur l'intelligence artificielle permettant la recherche, la consultation, l'administration et la mise à jour de la base de connaissances.
---

## Production handoff

Le dossier de passation production pour l'équipe IT / infrastructure est disponible ici :

- [Production Handoff](docs/production-handoff.md)

Il centralise les liens vers les checklists de déploiement, l'inventaire GitHub Environment, les runbooks backup/restore et opérations, les limitations connues, la checklist de lancement, la matrice de responsabilités et le template Nginx. Le déploiement production nécessite une validation IT explicite.

---

#Présentation

Cette plateforme a pour objectif de centraliser l'ensemble des procédures métier FDE et de fournir aux agents un moteur de recherche intelligent capable de retrouver rapidement les informations pertinentes grâce à une architecture RAG (Retrieval-Augmented Generation).

Elle est composée de deux espaces distincts :

- Console Agent
- Console Administrateur

---

# Fonctionnalités 

## Console Agent 

- Recherche sémantique
- Recherche par mots-clés
- Chat IA assisté par LLM local (Ollama)
- Réponses contextualisées
- Sources citées automatiquement
- Historique des recherches

## Console Administrateur

- Tableau de bord de supervision
- Surveillance de l'état de la plateforme
- Statistiques de la base documentaire
- Journal des recherches
- Import de nouveaux articles DOCX
- Mise à jour automatique de la base de connaissances

---

Architecture Technique 

##Frontend 

- React
- TypeScript
- Vite

## Backend

- FastAPI
- SQLAlchemy
- PostgreSQL
- Milvus
- Sentence Transformers
- Ollama

---

# Architecture Fonctionnelle


                        Article DOCX
                              │
                              ▼
                     Analyse du document
                              │
                              ▼
               Découpage intelligent (Chunking)
                              │
                              ▼
                   Génération des embeddings
                              │
                              ▼
                    PostgreSQL (Métadonnées)
                              │
                              ▼
                    Milvus (Index vectoriel)
                              │
                              ▼
                     Recherche sémantique
                              │
                              ▼
                          LLM (Ollama)
                              │
                              ▼
                        Réponse finale

---
# Modules Disponibles

## Agent

- Recherche intelligente
- Chat IA
- Historique

## Administration

- Vue d'ensemble
- Santé système
- Audits
- Statistiques
- Mise à jour de la base

---

# API REST 

## Recherche 
POST /api/v1/search
POST /api/v1/keyword-search
POST /api/v1/chat


## Supervision


GET /api/v1/health
GET /api/v1/stats


## Audits


GET /api/v1/audit/retrievals/latest
GET /api/v1/audit/retrievals/{id}


## Gestion de la base de connaissances


POST /api/v1/admin/ingestion/docx
GET /api/v1/admin/ingestion/jobs
GET /api/v1/admin/ingestion/jobs/{job_id}


---

# Pipeline de Mise à Jour 

Le module d'administration permet d'importer un nouvel article de connaissance au format DOCX.

Chaque import déclenche automatiquement :

- Analyse du document
- Validation de la structure
- Découpage en chunks
- Génération des embeddings
- Indexation PostgreSQL
- Indexation Milvus
- Publication immédiate (MVP)

Les doublons sont détectés automatiquement afin d'éviter toute réindexation inutile.

---

# État actuel du projet

| Module | État |
|---------|------|
| Landing Page | ✅ Terminé |
| Authentification (Interface) | ✅ Terminé |
| Console Agent | ✅ Terminé |
| Console Administrateur | ✅ Terminé |
| Recherche Sémantique | ✅ Terminé |
| Recherche par mots-clés | ✅ Terminé |
| Chat IA (Ollama) | ✅ Terminé |
| PostgreSQL | ✅ Terminé |
| Milvus | ✅ Terminé |
| Journalisation | ✅ Terminé |
| Santé système | ✅ Terminé |
| Statistiques dynamiques | ✅ Terminé |
| Import DOCX | ✅ Terminé |
| Détection de doublons | ✅ Terminé |
| Authentification Backend | 🚧 En cours |
| Gestion des rôles (RBAC) | 🚧 En cours |
| Validation des articles | ⏳ À venir |
| Publication des articles | ⏳ À venir |
| Gestion des versions | ⏳ À venir |

---
# Installation

## Backend

bash
python -m venv venv

source venv/bin/activate
# ou
venv\Scripts\activate

pip install -r requirements.txt

uvicorn app.main:app --reload

## Frontend

bash
cd frontend

npm install

npm run dev

---

# Lancement avec Docker

bash
docker compose up -d

# Captures d'écran
# Captures d'écran

## Landing Page

![Landing Page](screenshots/landing.png)

---

## Authentification

![Authentification](screenshots/login.png)

---

## Console Agent

![Console Agent](screenshots/agent-chat.png)

---

## Tableau de bord Administrateur

![Dashboard](screenshots/admin-dashboard.png)

---

## Santé Système

![Santé Système](screenshots/system-health.png)

---

## Audits

![Audits](screenshots/audits.png)

---

## Statistiques

![Statistiques](screenshots/statistics.png)

---

## Mise à jour de la base

![Mise à jour](screenshots/update-kb.png)

---

# Évolutions prévues

- Authentification JWT
- Gestion des rôles (RBAC)
- Workflow de validation
- Workflow de publication
- Gestion des versions des documents
- Import Excel
- Gouvernance documentaire
- Tableau de bord analytique avancé

---

# Licence

Projet interne réalisé dans le cadre du développement de la plateforme de gestion des connaissances FDE pour Sogetrel.
