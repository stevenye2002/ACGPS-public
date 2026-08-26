# ACGPS v1.0 Core Scope

## In scope

- Python CLI application.
- Local, single-user operation.
- Human-supervised local development on Windows Server 2022 with Python 3.13.
- Project registration through project profiles.
- Structured task intake.
- Deterministic workflow state machine.
- Rule-based risk classification with optional model recommendation as non-authoritative input.
- Human decision queue and decision records.
- Read-only CLI inspection of pending human decisions.
- Skill routing recommendations and mandatory-gate calculation.
- Model-role routing recommendations.
- Planner, Coder, Reviewer, and Verifier task-packet generation.
- Evidence requirements and transition validation.
- Append-only audit log.
- Integration with existing `PROJECT_STATE`, implementation-plan, review-kit, and quality-check conventions.
- FTIC project profile and one real dogfood workflow.
- Bounded-executor contracts and validation surfaces retained as implemented,
  unqualified, and disabled by default.

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
- Autonomous model execution or bounded-executor P4/P5 qualification.
- Live trading, broker credentials, or co-location with an MT4/MT5 execution boundary.

## v1.0 core delivery unit

A supervised CLI and file contract capable of taking one FTIC governance or engineering task through:

`INTAKE -> CLASSIFIED -> SPEC_READY -> PLAN_READY -> IMPLEMENTING -> REVIEW -> VERIFIED -> RC_READY`

The flow must expose pending records when it pauses at `WAITING_HUMAN`, resume
only from a matching human decision, and never authorize production release.

## Technology constraints

- Standard-library-first Python implementation.
- External dependencies require explicit justification in the implementation plan.
- Data contracts must be versioned.
- Runtime state and durable project records must be clearly separated.
- All tests must run locally without paid external services.
