# ADR-0005: Card Agent runtime, confirmation, and transaction ownership

- Status: Accepted
- Date: 2026-10-18
- Owners: FinOrch maintainers

## Context

Phase 1B needs one runnable, reviewable AI Banking Agent slice that reuses the Phase 1A Card Application and SQLite database. The slice must distinguish a deterministic demo from model inference, persist task/tool state, require server-side confirmation for card writes, preserve a single write boundary, and avoid an orchestration framework before there is evidence it is needed.

## Decisions

1. Keep the modular monolith and implement a bounded single-Agent loop with a typed allowlist Tool Registry. The initial registered tools are `card.list`, `card.get`, `card.freeze`, and `card.unfreeze`; model output cannot register tools or access SQLAlchemy directly.
2. Use a `FakeProvider` as the default deterministic local/demo mode. It performs no network access and is not described as LLM inference. Add a provider interface and an opt-in OpenAI-compatible Chat Completions Tool Calling adapter. The adapter has mock HTTP coverage; no live provider call is part of Phase 1B acceptance.
3. Persist `agent_tasks`, `task_steps`, `tool_executions`, and one-time `confirmation_challenges`. Extend `audit_events` to a generic append-only event shape while preserving card status columns and migrating historical rows. Keep user-facing API DTOs separate from ORM models.
4. Route all card writes through `confirm_card_change`. The challenge binds actor, card, tool name/version, target status, normalized parameter digest, card version, policy version, idempotency key, expiry, and consumption state. The server rechecks the bindings when confirming.
5. Keep transaction ownership in the lightweight `application.transactions.write_transaction` helper rather than introducing a general Repository/UoW framework. A top-level write use case owns commit/rollback; nested Application writes join the explicit unit of work. A clean SQLAlchemy read-autobegin is ended before a new write transaction; untracked pending writes are rejected.
6. Use SQLite `BEGIN IMMEDIATE` around confirmation and idempotency decisions so competing local writes serialize. Confirmation consumption, card mutation, workflow result, and corresponding audit event commit or roll back together. SQLite remains a local demo/CI database, not a production concurrency promise.
7. Keep task progress REST-based. Do not add LangGraph, MCP, Redis, a job queue, SSE, or WebSockets for this slice.

## Consequences

- The UI can demonstrate a real server-owned confirmation and card status change with no external model key.
- The configured real-provider path is available for opt-in testing, but its live model behavior, vendor data handling, and prompt-injection resistance remain unverified. Use synthetic demo data and a trusted endpoint only.
- SQLite serializes local writes; higher-concurrency deployment or a different database requires measured evidence and a new decision.
- Demo Identity remains limited to development/test and is not production authentication.

## Validation

The decision is implemented by Alembic migration `0002_agent_workflow_and_audit`, the `agent/` and `application/agent.py` modules, `application/transactions.py`, and their API/integration tests. Full verification results are recorded in the Phase 1B pull request.
