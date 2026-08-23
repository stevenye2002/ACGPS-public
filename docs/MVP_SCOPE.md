# ACGPS v0.1 Scope

## In scope

- Python CLI application.
- Local, single-user operation.
- Project registration through project profiles.
- Structured task intake.
- Deterministic workflow state machine.
- Rule-based risk classification with optional model recommendation as non-authoritative input.
- Human decision queue and decision records.
- Skill routing recommendations and mandatory-gate calculation.
- Model-role routing recommendations.
- Planner, Coder, Reviewer, and Verifier task-packet generation.
- Evidence requirements and transition validation.
- Append-only audit log.
- Integration with existing `PROJECT_STATE`, implementation-plan, review-kit, and quality-check conventions.
- FTIC project profile and one real dogfood workflow.

## Explicit non-goals

- Web UI or dashboard.
- Multi-user or multi-tenant operation.
- Direct billing, quota management, or model marketplace.
- Automatic production deployment.
- Autonomous acceptance of legal, financial, medical, privacy, or security risk.
- Replacing Git, CI, issue trackers, Figma, Superpowers, or project-specific tools.
- Embedding domain logic for FTIC, FIC, GSIS, GAPS, GIQTS, or HSIPS in the ACGPS core.
- A general long-term-memory or vector-database platform.
- Automatic prioritization of product ideas without human ownership.

## MVP delivery unit

A CLI and file contract capable of taking one FTIC governance or engineering task through:

`INTAKE -> CLASSIFIED -> SPEC_READY -> PLAN_READY -> IMPLEMENTING -> REVIEW -> VERIFIED -> RC_READY`

The flow must pause at `WAITING_HUMAN` only for policy-defined decisions and must not authorize production release.

## Technology constraints

- Standard-library-first Python implementation.
- External dependencies require explicit justification in the implementation plan.
- Data contracts must be versioned.
- Runtime state and durable project records must be clearly separated.
- All tests must run locally without paid external services.
