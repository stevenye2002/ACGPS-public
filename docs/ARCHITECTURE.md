# Architecture

The v0.1 architecture is defined in `docs/SYSTEM_DESIGN.md`. This document summarizes the review-facing structure.

## Components

- CLI entry points execute setup, validation, and workflow commands.
- File-backed contracts store task intake, task state, risk assessments, routing decisions, human decisions, agent task contracts, results, review findings, verification records, audit events, and release candidate manifests.
- Policy files in `config/` provide workflow, risk, human decision, skill routing, and model routing inputs.
- Review artifacts under `reviews/` preserve external feedback, finding responses, verification evidence, and review package records.

## Authority Boundary

The workflow controller is responsible for transition authorization. Agents may recommend transitions, but they do not self-approve their own outputs.

## Persistence Boundary

All v0.1 state is local and file-backed. Append-only audit events are required for transitions and material review events.
