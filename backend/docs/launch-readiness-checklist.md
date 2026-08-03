# Launch Readiness Checklist

Status values:

- **READY**
- **READY WITH ACCEPTED RISK**
- **BLOCKED**
- **NOT VALIDATED**
- **REQUIRES IT**

## Product

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Agent search/chat workflow | READY | Routes `/api/v1/search`, `/api/v1/keyword-search`, `/api/v1/chat`, `/api/v1/chat/stream`; frontend Agent page exists. | Application developer | Blocking |
| Source article view and original DOCX download | READY | Routes `/api/v1/knowledge/articles/{source_document_id}` and `/api/v1/knowledge/documents/{source_document_id}/original`. | Application developer | Blocking |
| Admin dashboard and analytics | READY | Admin analytics routes and frontend panels exist. | Application developer | Blocking |
| Business answer-quality acceptance | NOT VALIDATED | Benchmark docs exist, but no production business signoff is recorded here. | Business knowledge owner | Blocking for broad rollout |

## Security

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Local JWT auth and Argon2 password hashing | READY | `backend/app/security.py`, `backend/app/auth_routes.py`. | Application developer | Blocking |
| Role authorization | READY | `admin` and `agent` dependencies in `backend/app/auth_dependencies.py`. | Application developer | Blocking |
| Security workflow | READY | `.github/workflows/security.yml` defined; context says green. | Security team/application developer | Blocking |
| React Router advisory exception | READY WITH ACCEPTED RISK | Scoped exception expires 2026-08-17. | Security team/application developer | Blocking after expiry |
| Production TLS/security headers | REQUIRES IT | Nginx template provided; no live config installed by this phase. | IT/deployment team/security team | Blocking |

## Identity

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Entra ID / SSO | BLOCKED | Not implemented. | Security team/IT deployment team | Blocking for SSO requirement |
| Invitation lifecycle | READY WITH ACCEPTED RISK | App supports activation tokens, but only `noop`/`capture` delivery modes. | Application developer/platform administrator | Blocking if email delivery is required |
| Password reset lifecycle | READY WITH ACCEPTED RISK | App supports reset tokens, but no production email provider. | Application developer/platform administrator | Blocking if self-service reset email is required |

## Data

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| PostgreSQL schema migrations | READY | Alembic chain has one head; PostgreSQL Integration workflow defined and green by context. | Application developer | Blocking |
| Original DOCX storage backup | REQUIRES IT | `KB_UPLOAD_ROOT` documented; backup implementation outside Git required. | IT/deployment team | Blocking |
| Milvus backup/regeneration strategy | REQUIRES IT | Runbook documents both strategies; no restore drill evidence. | IT/deployment team | Blocking |
| Redis source-of-truth decision | READY | Redis documented as rebuildable cache. | Application developer/IT deployment team | Non-blocking |

## Infrastructure

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| VM sizing | REQUIRES IT | Single-VM Compose requirements documented. | IT/deployment team | Blocking |
| DNS | REQUIRES IT | Checklist requires approved hostname and DNS. | IT/deployment team | Blocking |
| Firewall | REQUIRES IT | Checklist and Nginx template avoid direct internal service exposure. | IT/deployment team/security team | Blocking |
| Nginx/static hosting | REQUIRES IT | Template exists; installation/configuration not performed. | IT/deployment team | Blocking |

## Deployment

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Manual VM deployment workflow | READY | `.github/workflows/deploy-vm.yml` and `scripts/deploy_vm.sh`. | Application developer/IT deployment team | Blocking |
| Production environment approval | REQUIRES IT | Workflow uses `environment: production`; GitHub settings must enforce approval. | Management approver/IT deployment team | Blocking |
| Exact-SHA CI gate | READY | `.github/scripts/verify_deploy_ci.py`. | Application developer | Blocking |
| Deployment executed | NOT VALIDATED | This phase intentionally does not deploy. | IT/deployment team | Blocking for launch |

## Backup/Recovery

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Pre-deploy PostgreSQL backup | READY | Implemented in `scripts/deploy_vm.sh`. | Application developer/IT deployment team | Blocking |
| Restore drill | NOT VALIDATED | No evidence of successful restore rehearsal. | IT/deployment team | Blocking for broad rollout |
| Backup retention | REQUIRES IT | Recommendation documented; implementation outside Git. | IT/deployment team | Blocking |

## Observability

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| API health | READY | `/api/v1/health` returns component status. | Application developer | Blocking |
| Production monitoring/alerting | REQUIRES IT | Runbook commands exist; no monitoring stack configured. | IT/deployment team | Blocking for rollout beyond pilot |
| Log access | REQUIRES IT | Docker log commands documented; centralization not configured. | IT/deployment team | Non-blocking for controlled pilot |

## Performance

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Benchmark scripts/runbooks | READY | `performance-benchmark.md` and `ollama-model-benchmark.md`. | Application developer | Non-blocking |
| Production-like load test | NOT VALIDATED | No 50-user or 500-user evidence in repo. | IT/deployment team/application developer | Blocking for broad rollout |
| Ollama target hardware validation | NOT VALIDATED | Requires actual VM audit and benchmark. | IT/deployment team | Blocking for broad rollout |

## Operations

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Operations runbook | READY | `operations-runbook.md`. | Application developer/IT deployment team | Blocking |
| Incident ownership | REQUIRES IT | Responsibility matrix provided; company process needed. | IT/deployment team/management approver | Blocking |
| On-call/support process | REQUIRES IT | Not company-configured in repo. | Management approver/IT deployment team | Blocking for production |

## Compliance/Approvals

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Production deployment approval | REQUIRES IT | Explicitly required by handoff and workflow environment. | Management approver | Blocking |
| Security approval | REQUIRES IT | Security workflow exists; production risk signoff required. | Security team | Blocking |
| Data handling approval | REQUIRES IT | DOCX, audit, user, and retrieval data stores documented. | Security team/business knowledge owner | Blocking |

## Documentation

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Production handoff package | READY | `production-handoff.md` links all runbooks. | Application developer | Blocking |
| Nginx template | READY | `deployment/nginx/lab-ia-genius.conf.template`. | Application developer/IT deployment team | Blocking |
| GitHub environment inventory | READY | `github-production-environment.md`. | Application developer/IT deployment team | Blocking |

## Support

| Item | Status | Evidence | Owner | Blocking |
| --- | --- | --- | --- | --- |
| Platform administrator role | REQUIRES IT | App has admin role; named administrators not assigned here. | Platform administrator/management approver | Blocking |
| Knowledge-owner escalation | REQUIRES IT | Responsibility matrix identifies role only. | Business knowledge owner | Blocking for content issues |
| User support process | REQUIRES IT | No ticket queue/SLA configured in repo. | Management approver/platform administrator | Blocking for broad rollout |

## Final decision rules

Controlled pilot readiness:

- Allowed only when all blocking Product, Security, Data, Infrastructure, Deployment, Backup/Recovery, Operations, Compliance, Documentation, and Support items are `READY`, `READY WITH ACCEPTED RISK`, or formally accepted by the listed owner.
- `REQUIRES IT` items for DNS, TLS, firewall, VM, GitHub environment, secrets, Nginx/static hosting, and monitoring must be completed or explicitly accepted for pilot.
- Email delivery gaps may be accepted only if administrators have an approved manual account-lifecycle process.

50-user rollout readiness:

- Requires controlled pilot success, production monitoring/alerting, restore drill success, target-hardware Ollama validation, documented support process, and business answer-quality acceptance.
- No `BLOCKED` or unresolved blocking `NOT VALIDATED` items.

500-user rollout readiness:

- Requires production-like load testing for 500 users, capacity plan, restore drill evidence, monitoring with alert thresholds, incident process, security approval, and management approval.
- Single-VM and no-HA risks must be explicitly accepted or remediated.

Reasons to stop launch:

- CI gates are not green for the exact SHA.
- Production GitHub environment approval is missing.
- TLS/DNS/firewall/Nginx is incomplete.
- `/api/v1/health` is not JSON `status=healthy`.
- PostgreSQL backup or restore confidence is missing.
- Security owner blocks launch.
- Business knowledge owner rejects answer/source quality.
- No accountable production operator or support path is assigned.
