# ACGPS v1.0 Core Acceptance Criteria

## Functional

- `AC-001` A managed project can be registered from a versioned profile.
- `AC-002` A task intake can be validated and assigned a stable ID.
- `AC-003` Deterministic policy assigns an enforced risk level and required gates.
- `AC-004` Required skills and model roles are calculated without duplicate primary discovery workflows.
- `AC-005` A task cannot transition without required evidence.
- `AC-006` Human-decision conditions create a structured pending request and pause the task.
- `AC-007` Resolving a human decision resumes the correct state with an audit record.
- `AC-008` Role-specific task packets are generated with bounded context.
- `AC-009` Independent review findings can enter a fix-and-reverify loop.
- `AC-010` A release-candidate evidence manifest can be generated and validated.
- `AC-011` Production release remains blocked without explicit human authorization.
- `AC-012` All state-changing operations append audit events.
- `AC-013` Interrupted or corrupted workflow state either recovers from a valid audit prefix or fails closed with a recovery diagnostic.
- `AC-014` Pending human decisions are inspectable through a read-only CLI command and disappear after a matching recorded resolution resumes the task.
- `AC-015` Release readiness accepts only the Windows Server 2022 and Python 3.13 core-only platform boundary.

## Quality

- Invalid or missing configuration fails closed with actionable errors.
- State transitions are deterministic and unit tested.
- Schemas are versioned and reject incompatible inputs.
- No secrets are included in generated packets or review artifacts.
- The release-qualified CLI is usable on Windows Server 2022 with Python 3.13; portable tests may run on other systems without expanding the release claim.
- Core tests require no network or paid service.
- Documentation and configuration examples remain synchronized through tests.

## Dogfood

At least one FTIC task completes the pilot workflow with:

- intake;
- classification;
- generated role packets;
- implementation evidence;
- independent review;
- fresh verification;
- frozen review artifacts;
- audit trail;
- no unnecessary human question.
- no autonomous model execution, live trading, broker credential access, or managed-project write outside the approved task scope.
