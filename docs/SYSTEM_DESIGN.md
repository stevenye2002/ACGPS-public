# ACGPS System Design

## 1. Context

ACGPS sits above managed software projects. It does not own their domain logic. It reads project governance files, evaluates policy, creates bounded task packets, validates evidence, and controls lifecycle transitions.

## 2. Core components

### 2.1 CLI

Provides deterministic commands for project registration, task intake, status,
policy evaluation, read-only pending-decision inspection, decision-bound task
resumption, gate checks, task-packet generation, audit inspection, and review
preparation.

### 2.2 Project Profile Loader

Loads a versioned profile describing project paths, commands, critical contracts, risk overrides, project-specific skills, and release restrictions.

### 2.3 Workflow Engine

Maintains project-task lifecycle state and permits only policy-valid transitions. It never infers successful completion from model prose alone.

### 2.4 Policy Evaluator

Combines global workflow rules, risk rules, human-decision rules, skill-routing rules, model-routing rules, and project-profile overrides. Deterministic policy is authoritative; model assessments are advisory inputs.

### 2.5 Human Decision Queue

Creates structured decision requests, pauses affected transitions, records the owner's response, and supplies the resolved decision as immutable downstream context.

### 2.6 Task Packet Generator

Produces minimal, role-specific packets for Planner, Coder, Reviewer, and Verifier. Each packet contains only the task, binding constraints, relevant files, acceptance criteria, and required evidence.

### 2.7 Evidence Gate

Validates required artifacts such as specifications, plans, tests, check outputs, review findings, hashes, manifests, and human decisions before a transition is accepted.

### 2.8 Audit Ledger

Records append-only events for task creation, classification, transitions, decisions, evidence, overrides, review outcomes, and release authorization.

### 2.9 Review Adapter

Integrates with the existing frozen review-package workflow. It does not replace independent external or high-capability review.

## 3. Data locations

### ACGPS repository

Contains core code, global policies, schemas, templates, adapters, and tests.

### Managed project repository

Contains its own `AGENTS.md`, goal, project state, architecture, plans, tests, review records, and `acgps.project.yaml` profile.

### Runtime state

Operational state is stored under a clearly marked runtime directory and must not be confused with durable project documents. Durable decisions, reviews, and release evidence remain in the managed project's versioned governance directories.

## 4. Integration model

v1.0 core generates role task packets and commands for supervised operators.
The bounded coding executor remains implemented, unqualified, disabled by
default, and outside the v1.0 core release claim. Direct autonomous model
orchestration remains deferred, preserving separation between the workflow
contract and any subscription, model, or vendor.

### 4.1 Responsibility boundary

ACGPS owns approved-intent binding, policy and lifecycle authority, workflow state, candidate and evidence identity, independent review and verification gates, audit records, and human release-authorization records. The workflow controller remains the only component that may authorize an ACGPS state transition.

External execution runtimes own agent and model loops, tool invocation, session and context management, concrete sandbox enforcement, and multi-agent scheduling. Their completion states, logs, results, process exits, and approvals are evidence inputs rather than ACGPS authority.

An integration adapter may map existing ACGPS task, result, and evidence contracts to an external runtime and report the execution facts that runtime can support. It may not approve its own output, reinterpret missing runtime evidence as stronger assurance, or authorize a workflow transition. Any new adapter capability or contract change requires a separately approved design and qualification gate.

## 5. Security boundaries

- ACGPS may inspect repositories and execute configured validation commands.
- Destructive commands, production writes, external communications, credentials, and release actions require explicit policy and human authorization.
- Secrets must never enter task packets, logs, review bundles, or model prompts.
- Managed-project commands are allow-listed by profile.
- v1.0 core does not authorize autonomous model execution, live trading, broker credentials, or co-location with an MT4/MT5 execution boundary.

## 6. Failure behavior

- Invalid transition: fail closed and explain missing evidence.
- Ambiguous high-risk decision: create `WAITING_HUMAN` request.
- Model disagreement: use deterministic policy; escalate only if policy cannot decide.
- Verification failure: remain in or return to implementation/fix state.
- Corrupt or mismatched evidence: reject the transition.
- Controller failure: preserve the last valid state and append a recovery event.

## 7. Extensibility

Adapters may connect ACGPS to external execution runtimes and project tools, but they remain contract-preserving translators and evidence collectors. Vendor-specific invocation, sandbox, session, model, and multi-agent behavior remains outside the ACGPS core, and every adapter must preserve the same role, evidence, and authorization contracts.
