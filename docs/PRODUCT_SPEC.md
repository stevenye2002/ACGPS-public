# Product Specification

## Problem

Complex AI-assisted engineering projects can drift when planning, coding, review, verification, and human authority are handled as informal chat context. ACGPS provides a small, explicit workflow layer so progress is evidence-based and reviewable.

## v0.1 Product

ACGPS v0.1 is a CLI-first, local, single-user, file-backed control plane. It registers a managed project, records task intake, classifies risk, identifies required skills and gates, generates role-specific task packets, manages human decision requests, validates evidence, and prepares reviewable release-candidate material.

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

## Non-Goals

ACGPS v0.1 does not provide a web backend, multi-user permissions, direct model-provider orchestration, production deployment automation, or managed-project business logic.
