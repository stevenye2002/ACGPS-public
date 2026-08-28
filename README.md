# AI Coding Good Practice System (ACGPS)

ACGPS is an independent, reusable control plane for moving complex software projects from idea to deliverable software with minimal unnecessary human interruption.

It coordinates:

- product and risk decisions owned by humans;
- specification and architecture owned by a high-capability Planner;
- implementation owned by task-scoped Coding agents;
- independent review and evidence-based verification;
- deterministic workflow gates, audit records, and release authorization;
- conditional routing of Superpowers, Figma, deep-interview, browser, security, and project-specific skills.

## v1.0 core objective

Deliver a CLI-first, local workflow controller for human-supervised development on Windows Server 2022 with Python 3.13. It can register a project, intake a task, classify risk, determine required skills and gates, generate role-specific task packets, expose pending human decisions, validate evidence, and integrate with the existing review kit.

The bounded coding executor is included as an implemented but unqualified capability and is disabled by default. ACGPS v1.0 core does not authorize autonomous model execution, live trading, broker credentials, deployment, or release actions.

## Quick orientation

- Goal: `docs/PROJECT_GOAL.md`
- Scope: `docs/MVP_SCOPE.md`
- Design: `docs/SYSTEM_DESIGN.md`
- Security and privacy: `docs/SECURITY_AND_PRIVACY.md`
- Workflow states: `docs/WORKFLOW_STATE_MACHINE.md`
- Human decision policy: `docs/HUMAN_DECISION_POLICY.md`

## Validation

```bash
python -m pip install -r requirements.txt
python scripts/check.py setup
python scripts/check.py full
```

## Read-only task audit verification

An operator can verify the complete trusted audit lineage bound to the current
task-state identity without changing workflow state:

```powershell
python -m acgps task audit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The command validates every trusted generation from the current audit head back
to generation one, including event identity, sequence, hash-chain, predecessor,
and authoritative-tail bindings. It then re-reads the task state and fails
closed if its identity changed during the query. The JSON result reports only
the verified task identity, generation and event counts, and audit head; it
does not return the full audit transcript, launch a model or process, write
state, or authorize a workflow transition.

## Supervised planner handoff preview

Before choosing a workflow transition, an operator can inspect the current
task's legal next-state options and the actor and evidence ordering already
enforced by the controller:

```powershell
python -m acgps task next-action-preview <engine arguments> --task-id TASK_ID
```

The command opens the existing workflow store read-only and writes only its
JSON preview to stdout. It does not evaluate transition authorization, choose a
target, launch a model or process, or change workflow state. An option marked
`UNSPECIFIED_EXISTING_CONTRACT` has the controller's universal one-evidence
minimum but no more specific evidence ordering in the current contract; the
preview does not invent one.

When the task is in `WAITING_HUMAN`, the preview validates the authoritative
pending-decision queue and reports only the request's approved target `stage`.
The `pending_decision_requirement` field identifies the matching decision,
allowed option IDs, required resume state, and pause-by-default behavior. It is
not a resolution or transition authorization. Missing, foreign, duplicate, or
workflow-inapplicable pending-decision records fail closed without changing
state.

Before submitting a human decision resolution to `task advance`, an operator
can validate its canonical JSON contract and its binding to the authoritative
pending request:

```powershell
python -m acgps decision resolution-preview `
  --state-root path/to/state `
  --resolution path/to/decision-resolution.json
```

The preview writes JSON to stdout only. It verifies the complete pending queue
against authoritative `WAITING_HUMAN` task state, then reuses the existing
resolution validator to check decision, project, task, resume-state, and option
bindings. It does not resolve the decision, authorize or perform a workflow
transition, launch a model or process, or write state. `task advance` remains
the authoritative transition gate and revalidates the resolution when used.

After that contract-only check, an operator can preview the complete resume
Gate against the original pre-human transition contract:

```powershell
python -m acgps task resume-gate-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --to-state SPEC_READY `
  --actor PLANNER `
  --created-at-utc 2026-08-28T03:00:00Z `
  --decision-resolution path/to/decision-resolution.json `
  --evidence path/to/planner-packet.json `
  --evidence path/to/planner-result.json
```

The resume preview requires the exact authoritative pending decision and uses
the task's preserved `previous_state` to enforce the same actor and ordered
evidence contract that applied before the human pause. It rechecks task state,
trusted audit lineage, and pending-decision identity before returning. A
successful result still reports `authorization_status` as `NOT_GRANTED`; it
does not resolve the decision, write state, or reserve a later transition.
`task advance` performs the same resume validation again when separately
authorized.

After generating a canonical `PLANNER` task packet, an operator can validate
and preview the handoff without launching a model or writing workflow state:

```powershell
python -m acgps plan handoff-preview --packet path/to/planner-packet.json
```

After the supervised planner returns an `AGENT_RESULT` record, the operator can
validate its contract, role, packet identity, and safe relative file claims:

```powershell
python -m acgps plan result-receipt-preview `
  --packet path/to/planner-packet.json `
  --result path/to/planner-result.json
```

Both commands write only to stdout. They do not launch a process, change
workflow state, or authorize a transition to `SPEC_READY` or `PLAN_READY`;
those remain separate controller operations.

For those operator-authorized planning transitions, provide the same canonical
Planner packet first and canonical result second. The controller admits
`CLASSIFIED -> SPEC_READY` and `SPEC_READY -> PLAN_READY` only for actor
`PLANNER`, a `DONE` or `DONE_WITH_CONCERNS` result bound to the current
project/task packet, and a recommendation matching the requested target:

```powershell
python -m acgps task advance <engine arguments> `
  --task-id TASK_ID --to-state SPEC_READY --actor PLANNER `
  --created-at-utc 2026-08-27T00:00:00Z `
  --evidence path/to/planner-packet.json `
  --evidence path/to/planner-result.json
```

Use the same evidence order with `--to-state PLAN_READY` only after the task is
in `SPEC_READY` and the Planner result recommends `PLAN_READY`. Both evidence
files are SHA-256-bound into the append-only transition audit. These operations
do not launch a model or assess the semantic quality of the Planner's output.

## Supervised coder handoff preview

After generating a canonical `CODER` task packet, an operator can validate and
preview the handoff without launching a model or writing workflow state:

```powershell
python -m acgps coding handoff-preview --packet path/to/coder-packet.json
```

The command writes the preview to stdout only. The preview is not authority,
execution evidence, or permission to start a process; a human-supervised coder
session still requires separate operator authorization.

For the exact `PLAN_READY -> IMPLEMENTING` transition, the controller requires
actor `CODER` and the canonical Coder packet as the only evidence file. The
packet must preserve the accepted `PLAN_READY` Planner packet's complete task
boundary; only its deterministic `packet_id` and `role` change to `CODER`:

```powershell
python -m acgps task advance <engine arguments> `
  --task-id TASK_ID --to-state IMPLEMENTING --actor CODER `
  --created-at-utc 2026-08-27T00:00:00Z `
  --evidence path/to/coder-packet.json
```

The controller revalidates the trusted Planner audit binding and SHA-256-binds
the Coder packet before entering `IMPLEMENTING`. This gate does not launch a
model or authorize changes beyond the frozen task boundary. Other existing
paths back to `IMPLEMENTING` after review or human intervention are unchanged.

After the supervised coder returns an `AGENT_RESULT` record, an operator can
validate its contract and packet binding without launching a process or changing
workflow state:

```powershell
python -m acgps coding result-receipt-preview `
  --packet path/to/coder-packet.json `
  --result path/to/coder-result.json
```

The receipt preview hashes both records and rejects mismatched packet identities,
non-`CODER` records, and unsafe claimed file paths. It remains non-authoritative:
the reported next state is only the coder's recommendation, and a separate
operator-authorized workflow transition is still required.

For that operator-authorized transition, provide the same canonical packet first
and canonical result second. The controller admits `IMPLEMENTING -> TASK_REVIEW`
only for actor `CODER`, a `DONE` or `DONE_WITH_CONCERNS` result bound to the
current project/task packet, and an explicit `TASK_REVIEW` recommendation:

```powershell
python -m acgps task advance <engine arguments> `
  --task-id TASK_ID --to-state TASK_REVIEW --actor CODER `
  --created-at-utc 2026-08-27T00:00:00Z `
  --evidence path/to/coder-packet.json `
  --evidence path/to/coder-result.json
```

Both raw evidence files are SHA-256-bound into the append-only transition audit.
Entering `TASK_REVIEW` requests independent review; it does not verify, accept,
release, or execute the coder's result.

## Supervised reviewer preview

After generating a canonical `REVIEWER` task packet, an operator can validate
and preview the handoff without launching a model or writing workflow state:

```powershell
python -m acgps review handoff-preview --packet path/to/reviewer-packet.json
```

When the supervised reviewer returns an `AGENT_RESULT` record, the operator can
validate its contract, role, packet identity, and safe relative file claims:

```powershell
python -m acgps review result-receipt-preview `
  --packet path/to/reviewer-packet.json `
  --result path/to/reviewer-result.json
```

Both commands write only to stdout. They do not launch a process, change
workflow state, read or accept review findings, or authorize a transition from
`TASK_REVIEW`; those remain separate controller operations.

For an operator-authorized transition from `TASK_REVIEW`, provide the same
canonical Reviewer packet first, its canonical result second, and one or more
review-finding records after them. The controller admits `FIX_REQUIRED` or
`INTEGRATING` only when the Reviewer result is complete, bound to the current
project/task packet, and recommends that exact target state. Existing finding
severity and closure rules still apply, and every supplied evidence file is
SHA-256-bound into the transition audit.

To resume implementation from `FIX_REQUIRED`, use actor `CODER` and provide the
original plan-bound canonical Coder packet first, followed by every current
accepted or partially accepted open P0/P1 review finding in its trusted audit
order. The controller
rejects missing, reordered, additional, foreign, modified, or non-blocking
finding evidence and any Coder packet that expands the frozen `PLAN_READY` task
boundary. This transition records the remediation handoff; it does not launch a
model or alter the accepted findings.

## Supervised verifier preview

After generating a canonical `VERIFIER` task packet, an operator can validate
and preview the handoff without launching a model or writing workflow state:

```powershell
python -m acgps verify handoff-preview --packet path/to/verifier-packet.json
```

When the supervised verifier returns an `AGENT_RESULT` record, the operator can
validate its contract, role, packet identity, and safe relative file claims:

```powershell
python -m acgps verify result-receipt-preview `
  --packet path/to/verifier-packet.json `
  --result path/to/verifier-result.json
```

Both commands write only to stdout. They do not launch a process, change
workflow state, inspect verification records, or authorize `INTEGRATING ->
VERIFIED`; those remain separate controller operations.

For an operator-authorized `INTEGRATING -> VERIFIED` transition, provide the
same canonical Verifier packet first, its canonical result second, and one or
more verification records after them. The controller admits `VERIFIED` only
when the Verifier result is complete, bound to the current project/task packet,
and recommends `VERIFIED`. Existing verification-record identity and freshness
rules still apply, and every supplied evidence file is SHA-256-bound into the
transition audit. Record-only `VERIFIED` requests are rejected.

When verification instead identifies required corrections, an operator may
request `INTEGRATING -> FIX_REQUIRED` with actor `VERIFIER`. The same canonical
Verifier packet and result must be followed by verification records that all
recommend `FIX_REQUIRED`, identify the current project and task, and contain
failed requirements. The controller binds those records into the audit, and a
later Coder remediation handoff must provide the original plan-bound Coder
packet followed by those exact failed-verification records. This does not alter
the independent Reviewer evidence required for transitions from `TASK_REVIEW`.

This public source boundary contains the reusable v1.0 core product, the inherited v0.1 design
documents, deterministic checks, and test fixtures. Private development
decisions, review transcripts, proposal packs, and third-party research inputs
are intentionally not part of the distribution.

## v1.0 core release readiness

The v1.0 core release-readiness boundary is Windows Server 2022 with Python
3.13 in human-supervised local-development mode. Bounded-executor P4/P5
qualification and autonomous model execution are deferred. Ordinary unit tests
remain portable where their applicability boundary permits.

Build and verify the deterministic source artifact without publishing it:

```powershell
python scripts/build_mvp_source_archive.py . dist/acgps-v1.0-core-source.zip
python scripts/release_readiness.py --archive dist/acgps-v1.0-core-source.zip
python scripts/check.py release
```

`acgps rc prepare` requires at least one `--build-artifact` and records its
SHA-256 in the existing release-candidate manifest contract. An `RC_READY`
manifest is evidence for a later human release decision; it does not authorize
publishing, deployment, or production release.

Before requesting any direct state transition, an operator can validate the
current policy, required actor, and ordered evidence snapshots without changing
workflow state:

```powershell
python -m acgps task gate-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --to-state IMPLEMENTING `
  --actor CODER `
  --created-at-utc 2026-08-28T03:00:00Z `
  --evidence path/to/coder-packet.json
```

The command uses the same gate validation as `task advance`, but reports
`authorization_status` as `NOT_GRANTED` and performs no state write or workflow
transition. It rejects policy outcomes that require `WAITING_HUMAN`; use
`decision resolution-preview` for a task already waiting on a human decision.
Evidence and current state are revalidated if `task advance` is authorized
later.

An operator can independently revalidate an existing manifest and all of its
referenced source, build, verification, review, and rollback evidence without
rewriting any of them:

```powershell
python -m acgps rc verify `
  --manifest path/to/release-candidate.json `
  --expected-project-id PROJECT_ID `
  --expected-task-id TASK_ID `
  --require-build-artifacts
```

The optional identity arguments fail closed when the referenced evidence does
not belong to the expected project or task. `--require-build-artifacts` applies
the same build-artifact boundary used by `rc prepare`. The command writes only
its validation result to stdout and does not create, repair, authorize, or
release an RC.

Before requesting the state-changing `VERIFIED -> RC_READY` transition, an
operator can preview the complete task gate against the current workflow state,
policy, manifest snapshot, and trusted verification lineage:

```powershell
python -m acgps rc task-gate-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --manifest path/to/release-candidate.json `
  --actor VERIFIER `
  --created-at-utc 2026-08-28T03:00:00Z
```

The preview opens the workflow controller read-only and reuses the same policy,
actor, evidence-snapshot, manifest-identity, and latest `VERIFIED` audit-lineage
checks as `task advance`. A successful preview reports `authorization_status`
as `NOT_GRANTED`: it does not write state, create a decision, authorize release,
or reserve a later transition. `task advance` always revalidates current state
and evidence when an operator separately authorizes the transition.

After a task reaches `RC_READY`, its existing release-candidate manifest is also
the only accepted evidence for `RC_READY -> CLOSED`. Use `task gate-preview`
with `--to-state CLOSED`, actor `CONTROLLER`, and the exact manifest previously
bound by the trusted `RC_READY` audit event before separately requesting
`task advance`. The controller requires the same logical path, size, and SHA-256,
and revalidates the manifest, its referenced evidence, and the latest trusted
`VERIFIED` lineage after binding and again before commit. `CLOSED` records task
completion within the authorized scope; it does not authorize publishing,
deployment, tagging, or production release.

## Intended first pilot

FTIC is the first dogfood project. The v1.0 core pilot validates the supervised workflow and governance integration without changing FTIC's intelligence, evidence, forecast, report, trading, or broker behavior.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
