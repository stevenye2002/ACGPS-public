# Workflow State Machine

## Lifecycle stages

`IDEA -> DISCOVERY -> SPEC -> ARCHITECTURE -> PLAN -> IMPLEMENTATION -> INTEGRATION -> QA -> RC -> ACCEPTANCE -> RELEASE -> OPERATE`

A project may revisit an earlier stage when evidence invalidates an assumption, but the reason and superseded artifacts must be recorded.

## Task states

- `DRAFT`: intake exists but is incomplete.
- `READY_FOR_CLASSIFICATION`: required intake fields are complete.
- `CLASSIFIED`: risk, required gates, skills, and role routing are recorded.
- `SPEC_READY`: task specification and acceptance criteria exist.
- `PLAN_READY`: executable work package exists.
- `IMPLEMENTING`: a Coding agent is working.
- `TASK_REVIEW`: independent task review is active.
- `FIX_REQUIRED`: accepted findings require changes.
- `INTEGRATING`: task changes are combined and broader checks run.
- `SYSTEM_QA`: project-specific end-to-end or specialist QA is active.
- `VERIFIED`: required evidence is fresh and valid.
- `RC_READY`: release-candidate package is frozen.
- `WAITING_HUMAN`: a policy-defined decision blocks progress.
- `BLOCKED`: a non-human dependency blocks progress.
- `CLOSED`: task is complete within the authorized scope.
- `ABANDONED`: task was intentionally stopped with rationale.

## Mandatory transition rules

1. No classification without complete intake.
2. No implementation without acceptance criteria and an approved or policy-authorized plan.
3. No self-approval by the implementing role.
4. No verified state without fresh machine evidence.
5. No RC state without independent review and frozen artifacts.
6. No production release without explicit human authorization.
7. `WAITING_HUMAN` may resume only with a recorded decision.
8. Failed evidence returns the task to the narrowest state capable of correction.

## Autonomy behavior

Between human gates, the controller continues automatically. It does not ask “continue?” after each task. It pauses only for policy-defined decisions, irrecoverable blockers, or exhausted safe remediation paths.
