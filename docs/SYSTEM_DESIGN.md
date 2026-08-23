# ACGPS System Design

## 1. Context

ACGPS sits above managed software projects. It does not own their domain logic. It reads project governance files, evaluates policy, creates bounded task packets, validates evidence, and controls lifecycle transitions.

## 2. Core components

### 2.1 CLI

Provides deterministic commands for project registration, task intake, status, policy evaluation, decision handling, gate checks, task-packet generation, audit inspection, and review preparation.

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

v0.1 generates role task packets and commands for Codex or other agents. Direct provider API orchestration is deferred. This separates the workflow contract from any specific subscription, model, or vendor.

## 5. Security boundaries

- ACGPS may inspect repositories and execute configured validation commands.
- Destructive commands, production writes, external communications, credentials, and release actions require explicit policy and human authorization.
- Secrets must never enter task packets, logs, review bundles, or model prompts.
- Managed-project commands are allow-listed by profile.

## 6. Failure behavior

- Invalid transition: fail closed and explain missing evidence.
- Ambiguous high-risk decision: create `WAITING_HUMAN` request.
- Model disagreement: use deterministic policy; escalate only if policy cannot decide.
- Verification failure: remain in or return to implementation/fix state.
- Corrupt or mismatched evidence: reject the transition.
- Controller failure: preserve the last valid state and append a recovery event.

## 7. Extensibility

Adapters may later invoke model APIs, Figma, browser QA, security scanners, GitHub, deployment systems, or project-specific agents. All adapters must preserve the same role, evidence, and authorization contracts.
