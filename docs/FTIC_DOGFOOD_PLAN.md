# FTIC Dogfood Plan

## Goal

Validate ACGPS v0.1 on a real, complex project without changing FTIC domain behavior during the first pilot.

## Pilot 1 — Governance-only task

1. Register FTIC through `project_profiles/ftic.yaml`.
2. Load FTIC's goal, state, commands, contracts, and active review pointer.
3. Intake one governance or review-workflow improvement task.
4. Classify risk and required skills.
5. Generate Planner, Coder, Reviewer, and Verifier packets.
6. Run the task through the state machine.
7. Produce a frozen review package and audit trail.
8. Measure unnecessary human interruptions and missing gates.

## Pilot 2 — Bounded engineering task

Select a low-to-medium-risk FTIC engineering change that:

- has clear acceptance criteria;
- affects no production intelligence or forecast settlement;
- can be independently tested;
- exercises implementation and review loops.

## Pilot 3 — High-impact contract simulation

Use a non-production branch or synthetic task to test R2 behavior for a schema, evidence, or package-contract change. Confirm that required architecture, review, and human gates activate.

## Success metrics

- Human interruptions occur only for policy-defined reasons.
- No task skips required planning, testing, review, or verification.
- No duplicate discovery interview occurs.
- Reviewer context is bounded and independent.
- Frozen artifact hashes remain consistent.
- Activity can resume in a new session using concise project state.
- The workflow adds less overhead than the defects or ambiguity it prevents.

## Prohibited pilot behavior

- No automatic production release.
- No alteration of historical forecast or evidence records.
- No broad refactor of FTIC core code.
- No migration of all historical review files.
