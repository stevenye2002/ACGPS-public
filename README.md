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

## Supervised coder handoff preview

After generating a canonical `CODER` task packet, an operator can validate and
preview the handoff without launching a model or writing workflow state:

```powershell
python -m acgps coding handoff-preview --packet path/to/coder-packet.json
```

The command writes the preview to stdout only. The preview is not authority,
execution evidence, or permission to start a process; a human-supervised coder
session still requires separate operator authorization.

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

## Intended first pilot

FTIC is the first dogfood project. The v1.0 core pilot validates the supervised workflow and governance integration without changing FTIC's intelligence, evidence, forecast, report, trading, or broker behavior.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
