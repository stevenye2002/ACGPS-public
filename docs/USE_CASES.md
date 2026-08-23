# Use Cases

## UC-1 Intake A Managed Project Task

A human owner provides an approved task intent. ACGPS records the task using the task intake contract and moves it to classification only when required fields are present.

## UC-2 Classify Risk And Gates

The workflow controller evaluates task inputs against risk policy, records matched triggers, and determines whether human review, independent review, or verification is required before further progress.

## UC-3 Generate Role-Specific Work Packets

The Planner creates a bounded plan. The controller can produce task contracts for Coder, Reviewer, and Verifier roles with relevant paths, constraints, non-goals, and expected evidence.

## UC-4 Pause For Human Decision

When policy triggers human authority, ACGPS creates a structured human decision request and enters `WAITING_HUMAN` with a linked pending decision id.

## UC-5 Prepare Reviewable Evidence

After implementation and verification, ACGPS prepares review material that includes baseline identity, requirements, findings or responses, checks, and residual risks.
