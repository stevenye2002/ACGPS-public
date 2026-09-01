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

## Trusted project progress summary

An operator can obtain one read-only summary of every task owned by the selected
project profile:

```powershell
python -m acgps project progress-summary `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID
```

The command enumerates authoritative task-state rows in stable task-ID order,
selects tasks whose project identity matches the profile, and composes each from
the existing trusted audit-lineage and next-action summaries. It reports state
counts, the fixed control-store authority identity and generation, and the
per-task summaries. It fails closed if any authoritative task row is corrupt, if a task
summary does not match its enumerated state, or if the selected task set changes
during the query. The bounded revalidation window is not a global filesystem
snapshot. The command writes JSON only to stdout and does not write workflow
state, authorize a transition, or launch a model or process.

To verify a previously captured UTF-8 project summary against the current
trusted project state, keep the capture beneath the managed project or ACGPS
state root and run:

```powershell
python -m acgps project progress-summary-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --summary path/to/project-progress-summary.json
```

The verifier rejects ambiguous JSON keys and type-confused values, requires an
exact semantic match with the current trusted project summary, and rechecks
both the captured bytes and current project summary before returning their
bounded identity status. It reports the capture's path, size, and SHA-256 while
remaining read-only. The result covers the verification window; it is not a
global filesystem snapshot.

## Trusted project audit-lineage summary

An operator can project the existing audit-lineage verification for every task
owned by the selected project profile into one read-only result:

```powershell
python -m acgps project audit-lineage-summary `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID
```

The command reuses the trusted project progress summary's stable task-ID order,
project filtering, control-store authority, and final task-set identity check.
Each task entry is the existing `AUDIT_LINEAGE_VERIFIED` result; the command
does not reinterpret audit evidence, write workflow state, authorize a
transition, or launch a model or process. Its bounded revalidation window is
not a transaction-level snapshot of every project audit lineage at one instant.

To verify a previously captured UTF-8 audit-lineage summary against the current
trusted project state, keep the capture beneath the managed project or ACGPS
state root and run:

```powershell
python -m acgps project audit-lineage-summary-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --summary path/to/project-audit-lineage-summary.json
```

The verifier rejects ambiguous JSON keys and type-confused values, requires an
exact semantic match with the current trusted audit-lineage summary, and
rechecks both the captured identity and current project summary before
returning. It reports the capture path, size, and SHA-256 without writing state,
authorizing a transition, or launching a model or process. The result covers
the bounded verification window; it is not a global transaction snapshot.

## Trusted project next-action queue

An operator can project every task's existing trusted next-action preview into
one project-wide read-only queue:

```powershell
python -m acgps project next-action-queue `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID
```

The command preserves the trusted project summary's stable task-ID order,
control-store authority, state counts, and final task-set identity check. Each
queue item is the existing task next-action preview, including terminal tasks
whose legal `options` list is empty. It does not prioritize tasks, select or
authorize a transition, launch a model or process, or write workflow state.

To verify a previously captured UTF-8 queue against the current trusted project
state, keep the capture beneath the managed project or ACGPS state root and run:

```powershell
python -m acgps project next-action-queue-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --queue path/to/project-next-action-queue.json
```

The verifier rejects ambiguous JSON keys, requires an exact semantic match with
the current trusted queue, and rechecks both the captured bytes and current
queue before returning their bounded identity status. It reports the capture's
path, size, and SHA-256 without writing workflow state, authorizing a
transition, or launching a model or process. The result covers the verification
window; it is not a global filesystem snapshot.

## Trusted project pending-decision queue

To inspect the complete pending human-decision requests for only the selected
project profile, run:

```powershell
python -m acgps project pending-decision-queue `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID
```

The command returns the existing validated `human_decision_request` records in
stable task-ID order. It requires an exact one-to-one match between those
records and the project's trusted `WAITING_HUMAN` task states, then rechecks the
project task set and complete decision records before returning. Any mismatch
or drift fails closed. The bounded revalidation window is not a cross-store
atomic snapshot. The command writes only JSON to stdout and does not resolve a
decision, authorize a transition, write workflow state, or launch a model or
process.

To verify a previously captured UTF-8 pending-decision queue against the
current trusted project state, keep the capture beneath the managed project or
ACGPS state root and run:

```powershell
python -m acgps project pending-decision-queue-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --queue path/to/project-pending-decision-queue.json
```

The verifier rejects ambiguous JSON keys and type-confused values, requires an
exact semantic match with the current trusted pending-decision queue, and
rechecks both the captured bytes and current queue before returning their
bounded identity status. It reports the capture's path, size, and SHA-256
without resolving a decision, writing workflow state, authorizing a transition,
or launching a model or process. The result covers the verification window; it
is not a cross-store atomic snapshot.

To preview a proposed human-decision resolution against that same current
trusted project queue, keep the canonical JSON resolution beneath the managed
project or ACGPS state root and run:

```powershell
python -m acgps project pending-decision-resolution-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --resolution path/to/decision-resolution.json
```

The preview reuses the existing `human_decision_resolution` validator and
requires its pending request to appear exactly once in the current trusted
project queue. Before returning, it rechecks both the resolution file identity
and the complete project queue. The output records the resolution path, size,
SHA-256, and bounded identity status, but leaves authorization as
`NOT_EVALUATED`; it does not resolve the decision, advance workflow state, or
launch a model or process. `task advance` remains the authoritative transition
gate and revalidates the resolution if execution is later authorized.

To verify a captured preview against the current trusted project state, run:

```powershell
python -m acgps project pending-decision-resolution-preview-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --preview path/to/captured-pending-decision-resolution-preview.json
```

The verifier resolves the captured preview's existing resolution identity only
beneath the managed project or ACGPS state root, recomputes the trusted preview,
and requires an exact type-preserving semantic match. It then rechecks both the
captured preview and current trusted preview before returning their bounded
identity status. It leaves authorization as `NOT_EVALUATED` and performs no
workflow transition, persistent state write, model execution, or process
launch. The result covers the verification window; it is not a cross-store
atomic snapshot.

To compose that captured project preview with the existing read-only
`WAITING_HUMAN` resume Gate, run:

```powershell
python -m acgps project pending-decision-resolution-to-resume-gate-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --preview path/to/captured-pending-decision-resolution-preview.json `
  --actor PLANNER `
  --created-at-utc 2026-08-28T01:04:00Z `
  --evidence path/to/planner-packet.json `
  --evidence path/to/planner-result.json
```

The command verifies the captured project preview, resolves its already-bound
decision resolution, and passes that exact task, target, actor, and evidence to
the existing resume Gate. It then verifies the captured preview and resolution
again before returning the unchanged `WAITING_HUMAN_RESUME_GATE_PREVIEW`
contract. Authorization remains `NOT_GRANTED`; the command does not resolve the
decision, write workflow state, perform a transition, or launch a model or
process. A separately authorized `task advance` remains the only state-changing
path.

To verify a captured resume Gate preview against current trusted project state,
replay the exact inputs used to create it:

```powershell
python -m acgps project pending-decision-resolution-to-resume-gate-preview-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --gate-preview path/to/captured-project-resolution-resume-gate-preview.json `
  --preview path/to/captured-pending-decision-resolution-preview.json `
  --actor PLANNER `
  --created-at-utc 2026-08-28T01:04:00Z `
  --evidence path/to/planner-packet.json `
  --evidence path/to/planner-result.json
```

The Gate preview does not embed every policy input, so verification requires
the original actor, timestamp, evidence, risk triggers, human triggers, and
task attributes. The command uses a type-preserving canonical JSON comparison,
then rechecks the captured file and recomputes the current Gate before returning.
It performs no decision resolution, workflow transition, persistent state write,
model execution, or process launch. The result covers a bounded verification
window; it is not a cross-store atomic snapshot.

## Policy-bound task packet generation

After a task has reached `CLASSIFIED`, an operator can generate a role packet
from the unique accepted classification policy in the trusted audit lineage:

```powershell
python -m acgps packet generate `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --role PLANNER `
  --created-at-utc 2026-08-29T00:00:00Z `
  --output packets/planner.json
```

The command reads workflow state and audit lineage without mutation and copies
the accepted policy's required skills and mandatory gates into the packet. It
fails closed before writing the requested output when the classification
policy is missing, ambiguous, corrupt, or changes identity during lookup. The
only runtime write is the requested packet beneath `state-root`; the packet
contract does not claim a separately self-verifying policy-lineage identity.

An operator can later verify that a canonical task packet is exactly the packet
currently derived from the trusted task intake and unique accepted
classification policy:

```powershell
python -m acgps packet verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --packet path/to/packet.json
```

The verifier reads the packet and intake as canonical JSON snapshots, validates
the existing packet contract, regenerates the expected packet, and requires an
exact match. Before returning it rechecks the packet, intake, task-state, and
audit-lineage identities. It writes only its JSON result to stdout and does not
authorize a handoff or workflow transition. Verification proves current trusted
derivation; it does not establish when or by which process the packet was
originally created, and it does not validate the contents of `relevant_paths`.

To compose that verification with the existing supervised handoff preview for
the packet's declared Planner, Coder, Reviewer, or Verifier role:

```powershell
python -m acgps packet trusted-handoff-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --packet path/to/packet.json
```

The command verifies the current trusted packet, builds the matching existing
role handoff preview, then rechecks the packet and complete trusted verification
identity before returning both results to stdout. It does not write state,
launch a model or process, authorize the role handoff, or perform a workflow
transition. As with packet verification, it validates the path syntax in
`relevant_paths`, not the referenced file contents.

After the supervised role returns an `AGENT_RESULT`, an operator can compose
the same current-trusted packet verification with the matching existing result
receipt preview:

```powershell
python -m acgps packet trusted-result-receipt-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --packet path/to/packet.json `
  --result path/to/agent-result.json
```

The command canonical-reads both records, selects the Planner, Coder, Reviewer,
or Verifier receipt validator from the packet role, and rechecks both record
identities and the complete trusted packet verification before returning to
stdout. It does not write state, launch a model or process, authorize the
result's recommended next state, or perform a workflow transition. Claimed
result paths are syntax-validated but their file contents are not inspected.

To compose that trusted receipt with the existing read-only transition gate,
use the same packet and result and append any evidence already required by the
role's transition contract:

```powershell
python -m acgps packet trusted-result-transition-gate-preview `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --packet path/to/packet.json `
  --result path/to/agent-result.json `
  --created-at-utc 2026-08-29T05:00:00Z `
  --evidence path/to/required-review-or-verification-record.json
```

The command derives the target from `recommended_next_state` and the actor from
the trusted packet role; neither can be overridden. It accepts only existing
role-result evidence contracts: Planner planning gates, Coder entry to
`TASK_REVIEW`, Reviewer outcomes from `TASK_REVIEW`, and Verifier outcomes that
already require a Verifier result. Reviewer findings or verification records
remain explicit ordered `--evidence` arguments. Generic, handoff-only, closure,
release-candidate, and `WAITING_HUMAN` paths fail closed. Before returning, the
command rechecks the complete trusted receipt identity. Its nested gate result
still reports `authorization_status: NOT_GRANTED` and performs no state write,
model or process launch, or workflow transition.

After an operator has separately authorized the transition, the same trusted
Packet/Result composition can advance the task through the existing workflow
contract:

```powershell
python -m acgps packet trusted-result-transition-advance `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID `
  --packet path/to/packet.json `
  --result path/to/agent-result.json `
  --created-at-utc 2026-08-29T06:00:00Z `
  --evidence path/to/required-review-or-verification-record.json
```

The command derives both actor and target from the trusted records and accepts
the same Planner, Coder, Reviewer, and Verifier result transitions as the
read-only Gate preview. It does not admit generic, handoff-only, closure,
release-candidate, or `WAITING_HUMAN` paths. Packet, Result, current task/audit
identity, policy authorization, and ordered evidence are bound to one prepared
transition and checked again immediately before the existing atomic workflow
state/audit commit. A human Gate or any identity drift fails before that commit.
The command does not launch a model or external process; its only product state
write is the accepted transition's existing workflow state/audit transaction.

To revalidate the resulting authoritative audit tail without changing workflow
state, use:

```powershell
python -m acgps packet trusted-result-transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The verifier requires the current authoritative audit tail itself to be a
supported Planner, Coder, Reviewer, or Verifier Packet/Result transition. It
derives the complete evidence set from that tail, revalidates every bound path,
size, SHA-256, Packet/Result contract, target recommendation, and additional
Gate evidence, then rechecks task-state and audit-lineage identity before
returning JSON to stdout. It does not search older transitions, write state,
launch a model or process, or authorize another transition.

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

## Trusted task progress summary

An operator can combine the current trusted audit identity with the existing
next-action preview in one read-only progress report:

```powershell
python -m acgps task progress-summary `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The command verifies the complete audit lineage and derives the current legal
next actions, including any authoritative pending human-decision requirement.
It then repeats both reads and fails closed if the task, audit, or pending
decision identity changed during the summary. The consistency guarantee is
limited to this bounded revalidation window; it is not a global filesystem
snapshot. The command writes JSON only to stdout and does not write workflow
state, authorize a transition, or launch a model or process.

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

After an authorized resume has been committed, an operator can revalidate that
the current audit tail is the exact `WAITING_HUMAN` resume transition:

```powershell
python -m acgps task resume-transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The verifier binds the current task and audit head to the preceding human-pause
event, its canonical pending request and resolved decision sidecar, the
decision record embedded in the committed audit event, and every ordered resume
evidence path, size, and SHA-256. It rechecks those identities before returning
and fails closed if the task or audit advances during the query. It does not
write state, resolve a decision, authorize another transition, or launch a
model or process.

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

After an operator has separately committed either the initial
`PLAN_READY -> IMPLEMENTING` handoff or the remediation
`FIX_REQUIRED -> IMPLEMENTING` handoff, the authoritative tail can be verified
without changing state:

```powershell
python -m acgps packet trusted-handoff-transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The verifier accepts only those two current audit-tail transitions. It derives
the complete evidence set from the tail, revalidates the Coder packet against
the frozen plan, and, for remediation, requires the exact current blocking
evidence. It then rechecks every path, size, SHA-256, task-state identity, and
audit-lineage identity before returning JSON to stdout. It does not search for
a different transition, write state, launch a model or process, or authorize a
subsequent workflow transition.

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

After a separately authorized `VERIFIED -> RC_READY` transition commits, an
operator can verify the authoritative committed transition without supplying a
replacement manifest:

```powershell
python -m acgps rc task-transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The command requires the trusted audit tail to be exactly a Verifier-authored
`VERIFIED -> RC_READY` transition with one bound release-candidate manifest. It
revalidates that manifest against its audit path, size, SHA-256, current task
identity, and latest trusted `VERIFIED` evidence lineage, then repeats the
evidence and state/audit identity checks before returning. It opens the
workflow controller read-only and does not write state, advance the workflow,
run a model or subprocess, or authorize publishing or release. Its result
asserts the existing manifest contract; it does not add stronger byte-identity
claims for manifest references that the current contract records only by path.

A verified task that does not require a release candidate can instead use the
existing direct `VERIFIED -> CLOSED` policy path. Use `task gate-preview` with
actor `CONTROLLER` and provide the exact canonical Verifier packet, Verifier
result, and verification records already bound—at the same logical paths and in
the same order—by the latest trusted `VERIFIED` audit event. The controller
revalidates that complete evidence lineage after binding and immediately before
commit. This path records completion within the authorized task scope; it does
not create an RC or authorize publishing, deployment, tagging, or release.

After a task reaches `RC_READY`, its existing release-candidate manifest is also
the only accepted evidence for `RC_READY -> CLOSED`. Use `task gate-preview`
with `--to-state CLOSED`, actor `CONTROLLER`, and the exact manifest previously
bound by the trusted `RC_READY` audit event before separately requesting
`task advance`. The controller requires the same logical path, size, and SHA-256,
and revalidates the manifest, its referenced evidence, and the latest trusted
`VERIFIED` lineage after binding and again before commit. `CLOSED` records task
completion within the authorized scope; it does not authorize publishing,
deployment, tagging, or production release.

After either supported closure commits, an operator can verify the authoritative
committed transition without resupplying evidence:

```powershell
python -m acgps task closed-transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The command accepts only `VERIFIED -> CLOSED` or `RC_READY -> CLOSED`, both
authored by `CONTROLLER`. It revalidates the evidence bound by the authoritative
audit tail against the existing closure contract, then repeats the evidence and
state/audit identity checks before returning. It opens the workflow controller
read-only and does not write state, advance the workflow, run a model or
subprocess, or authorize publishing, deployment, tagging, or release.

An operator that does not already know which committed-transition verifier
applies can use the unified read-only entry point:

```powershell
python -m acgps task transition-commit-verify `
  --policy-root path/to/acgps `
  --state-root path/to/state `
  --project-root path/to/project `
  --profile-id PROFILE_ID `
  --task-id TASK_ID
```

The command dispatches only to the existing trusted Packet/Result, Coder
handoff, `WAITING_HUMAN` resume, `VERIFIED -> RC_READY`, or supported
`CLOSED` committed-transition verifier. It returns that verifier's existing
result unchanged. Unsupported audit tails fail closed; the command does not
add a generic transition contract, write state, advance the workflow, launch a
model or process, or authorize any external action.

## Intended first pilot

FTIC is the first dogfood project. The v1.0 core pilot validates the supervised workflow and governance integration without changing FTIC's intelligence, evidence, forecast, report, trading, or broker behavior.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
