# AI Coding Good Practice System (ACGPS)

ACGPS is an independent, reusable control plane for moving complex software projects from idea to deliverable software with minimal unnecessary human interruption.

It coordinates:

- product and risk decisions owned by humans;
- specification and architecture owned by a high-capability Planner;
- implementation owned by task-scoped Coding agents;
- independent review and evidence-based verification;
- deterministic workflow gates, audit records, and release authorization;
- conditional routing of Superpowers, Figma, deep-interview, browser, security, and project-specific skills.

## v0.1 objective

Build a CLI-first, file-backed workflow controller that can register a project, intake a task, classify risk, determine required skills and gates, generate role-specific task packets, maintain a human decision queue, validate evidence, and integrate with the existing review kit.

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

This public source boundary contains the reusable v0.1 product, stable design
documents, deterministic checks, and test fixtures. Private development
decisions, review transcripts, proposal packs, and third-party research inputs
are intentionally not part of the distribution.

## v0.1 release readiness

The v0.1 release-readiness boundary is Windows with Python 3.13. Linux release
qualification is deferred; the ordinary unit tests remain portable where their
applicability manifest requires both platforms.

Build and verify the deterministic source artifact without publishing it:

```powershell
python scripts/build_mvp_source_archive.py . dist/acgps-v0.1-source.zip
python scripts/release_readiness.py --archive dist/acgps-v0.1-source.zip
python scripts/check.py release
```

`acgps rc prepare` requires at least one `--build-artifact` and records its
SHA-256 in the existing release-candidate manifest contract. An `RC_READY`
manifest is evidence for a later human release decision; it does not authorize
publishing, deployment, or production release.

## Intended first pilot

FTIC is the first dogfood project. The initial pilot validates the workflow and governance integration without changing FTIC's intelligence, evidence, forecast, or report behavior.

## License

Licensed under the Apache License, Version 2.0. See `LICENSE`.
