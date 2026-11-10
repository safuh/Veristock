# Veristock One Architecture

Veristock One is a multi-tenant inventory verification platform with three browser workspaces: Veristock management, field operations and the client portal. It is implemented as a modular monolith: React + TypeScript browser application, FastAPI API, PostgreSQL and object storage.

## Architecture documents

- [Product architecture](PRODUCT_ARCHITECTURE.md) — runtime topology, module boundaries, tenancy, security, workflows, frontend workspaces, non-functional requirements and delivery sequence.
- [Domain model](DOMAIN_MODEL.md) — entities, relationships, lifecycle states, invariants and recommended migration order.
- [Architecture decision records](.) — durable technical decisions as they are accepted.

## Runtime dependency flow

```text
Management / Field / Client browser workspaces
                    |
                    v
             FastAPI /api/v1
                    |
        Authentication + RBAC
        Tenant/resource authorization
                    |
                    v
           Application use cases
                    |
          Domain modules/services
                    |
          Repository interfaces
                    |
          SQLAlchemy async adapters
                    |
               PostgreSQL

Files and evidence -> object storage abstraction
Alembic migrations -> explicit release operation
```

## Architectural rules

1. Keep a modular monolith for the MVP; do not split modules into microservices without measured need.
2. Routers handle HTTP concerns and delegate to application services.
3. Application services own use-case orchestration and transaction boundaries.
4. Tenant ownership and resource authorization are checked server-side on every protected operation.
5. Client-owned data must be isolated by organization membership and explicit resource scope.
6. Submitted count rounds, committed expected-stock snapshots and approved reconciliation runs are immutable/versioned facts.
7. Repositories use the session/transaction supplied by the application boundary.
8. SQLAlchemy models and Alembic migrations own persistence schema; migrations do not run in API workers.
9. Runtime configuration and secrets are injected by the environment.
10. Object storage access is authorized through the tenant-owned parent resource.
11. Frontend route visibility is not authorization; the API remains authoritative.
12. No AI, LLM, agent, vector database or AI-related scaffolding is included in the MVP.

## Product workspaces

- **Management:** clients, branches, workforce, quotations, engagements, assignments, QA, reporting and billing.
- **Field:** assigned work, blind counts, observations, condition/expiry capture, evidence, submissions and recounts.
- **Client:** organization/branch profile, inventory imports, assignment progress, approved results and reports.

## Existing foundation

The repository's existing FastAPI application factory, async SQLAlchemy persistence, Alembic setup, JWT primitives, Docker assets and tests are retained and extended. The previous backend-foundation-only scope is superseded by the product MVP architecture. Existing migrations must remain immutable; product schema changes are forward migrations.

## Explicit exclusions

AI integration, PydanticAI, LLM APIs, agents, embeddings/vector stores, native mobile apps, microservices, event streaming and mandatory Kubernetes deployment are not MVP requirements.
