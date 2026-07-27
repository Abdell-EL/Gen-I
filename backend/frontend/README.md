# Frontend — Plateforme de Gestion des Connaissances Sogetrel

![React](https://img.shields.io/badge/React-19-blue)
![TypeScript](https://img.shields.io/badge/TypeScript-6-blue)
![Vite](https://img.shields.io/badge/Vite-8-purple)
![Status](https://img.shields.io/badge/Status-Active-success)

Application React de la plateforme de gestion des connaissances FDE de Sogetrel.

Cette interface permet aux agents et aux administrateurs d'interagir avec le backend FastAPI à travers une expérience moderne, sécurisée et orientée entreprise.

---

# Technologies

- React 19
- TypeScript
- Vite
- React Router
- Axios
- Lucide React

---

# Fonctionnalités

## Landing Page

- Présentation de la plateforme
- Navigation
- Accès aux espaces Agent et Administrateur

---

## Authentification

- Connexion
- Inscription
- Protection des routes
- Gestion des rôles (mode démonstration / backend)

---

## Console Agent

- Recherche intelligente
- Chat IA
- Réponses générées par le LLM
- Sources utilisées
- Niveau de confiance
- Métadonnées de génération

---

## Console Administrateur

- Vue d'ensemble
- Santé de la plateforme
- Statistiques
- Journaux d'audit
- Mise à jour de la base documentaire

---

# Structure du projet

```
src/
│
├── app/
│   ├── AppRouter.tsx
│   ├── AuthContext.tsx
│   └── Route Guards
│
├── components/
│
├── features/
│   ├── admin/
│   └── chat/
│
├── pages/
│
├── services/
│
├── styles/
│
├── types/
│
└── assets/
```

---

# Communication avec le Backend

Le frontend communique avec le backend FastAPI via une API REST.

Principaux services utilisés :

- Authentification
- Chat IA
- Recherche
- Statistiques
- Santé système
- Audits
- Mise à jour de la base documentaire

Toutes les requêtes sont centralisées dans :

```
src/services/
```

---

# Lancement

Installation :

```bash
npm install
```

Développement :

```bash
npm run dev
```

Compilation :

```bash
npm run build
```

Lint :

```bash
npm run lint
```

---

# Variables d'environnement

Créer un fichier `.env` :

```env
VITE_API_BASE_URL=http://127.0.0.1:8000/api/v1
VITE_AUTH_MODE=demo
```

Pour utiliser la véritable authentification backend :

```env
VITE_AUTH_MODE=backend
```

---

# Fonctionnalités Implémentées

| Fonctionnalité | État |
|----------------|------|
| Landing Page | ✅ |
| Authentification | ✅ |
| Console Agent | ✅ |
| Console Administrateur | ✅ |
| Recherche IA | ✅ |
| Chat IA | ✅ |
| Audits | ✅ |
| Santé système | ✅ |
| Statistiques | ✅ |
| Import DOCX | ✅ |

---

# Améliorations Futures

- Authentification JWT
- Gestion des rôles (RBAC)
- Thème sombre
- Historique complet des conversations
- Notifications en temps réel
- Internationalisation

---

# Captures d'écran

À compléter avec les captures finales :

- Landing Page
- Authentification
- Console Agent
- Console Administrateur
- Santé Système
- Audits
- Statistiques
- Mise à jour de la base documentaire