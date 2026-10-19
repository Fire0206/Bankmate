# ADR-0006: Synthetic bill analysis and subscription lifecycle

- 状态：Accepted
- 日期：2026-10-19
- 决策人：FinOrch project maintainers

## 背景

Phase 1C adds bill analysis and subscription/recurring debit management while preserving the modular monolith and Agent confirmation workflow. The project needs deterministic results for demonstrations without connecting to real accounts, merchants, payment networks, or model-generated financial calculations.

## 决策

- Store synthetic transaction history in `transactions` as account-owned records with integer `amount_minor`, ISO currency, direction, category, merchant, and UTC timestamp. Transactions are analysis inputs, not ledger entries or balance authority.
- Compute monthly totals, categories, trends, and notices in the backend from those records. The current notice rule flags a non-housing expense of at least CNY 1,000; it is a demo rule, not fraud detection.
- Detect monthly subscription candidates from at least three equal-amount, same-currency charges for the same normalized merchant and account, each 25–35 days apart. Persist the detected candidate in `subscriptions`; derive the next simulated charge as 30 days after the latest detected charge.
- Keep subscription status changes synthetic and local. `subscription.pause`, `subscription.resume`, and `subscription.cancel` only create a server-side confirmation challenge. The shared Agent confirmation path revalidates actor ownership, resource version, policy/tool/input binding and idempotency before updating status and audit data in the same transaction.
- Reuse the existing Agent Task, ToolExecution, ConfirmationChallenge, Unit of Work and AuditEvent mechanism. The challenge points to exactly one supported resource (`card` or `subscription`) and records its resource version. Do not add a general event bus or external subscription connector.
- Seed and reset the deterministic dataset as `phase1c-v1` and manage the schema through a new Alembic revision; do not rewrite applied migration history.

## 备选方案

- Calculate bill totals in the model: rejected because results must be reproducible and derived from persisted records.
- Treat recurring transaction candidates as authoritative merchant mandates: rejected because transaction regularity alone cannot prove a real subscription or external cancellation capability.
- Add a general plugin/event framework or separate service: deferred until a demonstrated need warrants the added operational and coordination cost.

## 影响

- Frontend and Agent can share the same deterministic Application queries and confirmation path.
- Demo data must be labelled synthetic. Subscription recognition can produce false positives and the anomaly threshold can miss fraud; neither output is a financial or security judgment.
- Status changes do not stop any real-world payment. Future mandate semantics, confirmation risk policy, merchant integrations, retention, and production identity require separate design and review.
- OpenAPI snapshots and generated TypeScript types must be updated with API changes. Phase 1C migration, seed behavior and confirmation paths require automated tests.
