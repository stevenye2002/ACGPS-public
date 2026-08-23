# Risk Classification

## R0 — Trivial

Examples: spelling, non-behavioral documentation, formatting, isolated test metadata.

Required: focused check and lightweight review. No human gate.

## R1 — Normal engineering

Examples: bounded internal feature, ordinary bug, low-impact refactor, internal automation.

Required: lightweight specification, plan when multi-step, tests, independent review, affected checks. Human gate only if another trigger applies.

## R2 — High impact

Examples: public API, schema, persistence, user workflow, evidence chain, source package contract, core agent orchestration, external dependency.

Required: architecture assessment, explicit acceptance criteria, broad verification, independent high-capability review, RC evidence. Human decision for material trade-offs or residual risk.

## R3 — Critical

Examples: authentication, authorization, privacy, regulated or financial decisions, forecast logic, automated trading, production data, irreversible migration, signing, secret, or audit integrity, external production action.

Required: explicit human approval before implementation where appropriate, threat/risk analysis, strongest Planner and Reviewer, full verification, rollback plan, and human release authorization.

## Classification rules

- Choose the highest applicable level.
- Project profiles may raise but not silently lower global risk.
- A model may recommend a level; deterministic triggers and project overrides decide the enforced level.
- Risk changes during implementation must be reclassified and audited.
