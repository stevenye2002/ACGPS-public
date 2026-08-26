# Product Specification

## Problem

Complex AI-assisted engineering projects can drift when planning, coding, review, verification, and human authority are handled as informal chat context. ACGPS provides a small, explicit workflow layer so progress is evidence-based and reviewable.

## v1.0 Core Product

ACGPS v1.0 core is a CLI-first, local, single-user control plane for
human-supervised development on Windows Server 2022 with Python 3.13. It
registers a managed project, records task intake, classifies risk, identifies
required skills and gates, generates role-specific task packets, exposes and
manages human decision requests, validates evidence, and prepares reviewable
release-candidate material.

## Required Behaviors

- `REQ-001` ACGPS can register a managed project from a versioned profile.
- `REQ-002` ACGPS can validate task intake and assign stable task identity.
- `REQ-003` ACGPS classifies risk deterministically and calculates required gates.
- `REQ-004` ACGPS calculates required skills and model roles without duplicate primary discovery workflows.
- `REQ-005` The workflow controller blocks task transitions without required evidence.
- `REQ-006` Policy-defined human-decision conditions create a structured pending request and pause the task.
- `REQ-007` Resolving a human decision resumes the correct state with audit evidence.
- `REQ-008` ACGPS generates bounded role-specific Planner, Coder, Reviewer, and Verifier task packets.
- `REQ-009` Independent review findings can enter a fix-and-reverify loop with evidence-backed closure.
- `REQ-010` ACGPS can generate and validate release-candidate evidence manifests.
- `REQ-011` All state-changing operations append audit events.
- `REQ-012` The workflow controller can recover deterministically from interrupted or corrupted local workflow state without silently trusting invalid state.
- `REQ-013` A supervised operator can inspect pending human decisions through the CLI without editing runtime state.
- `REQ-014` Release-readiness evidence identifies the Windows Server 2022, Python 3.13, core-only product boundary.

## Non-Goals

ACGPS v1.0 core does not provide a web backend, multi-user permissions,
autonomous model execution, qualified bounded-executor P4/P5 containment,
production deployment automation, live trading, broker credential access, or
managed-project business logic.
