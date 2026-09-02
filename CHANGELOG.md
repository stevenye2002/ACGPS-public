# Changelog

## [Unreleased]

### v1.1 core release candidate

This section collects the proposed v1.1.0 changes. It is not a publication record;
the candidate still requires its own frozen review and human release authorization.

### Added

- Supervised Planner, Coder, Reviewer, and Verifier handoff/result previews, with
  trusted task-packet verification against accepted policy and intake lineage.
- Evidence-bound planning, implementation, review, verification, fix, human-resume,
  release-candidate, and closeout gates, with read-only gate previews and committed
  transition verification through a unified CLI entry point.
- Read-only trusted task/project progress, audit-lineage summaries, next-action
  and pending-decision queues, and human-resolution/resume previews.
- Captured-output verification for project summaries, queues, resolution previews,
  and the composed project assurance overview, including final identity rechecks
  and stale/drift rejection.
- A public specification-validation entry point using the existing contracts.

### Changed

- Clarified the runtime-neutral software-delivery assurance control-plane mission:
  narrow ownership of authorization enforcement, evidence, review, state, and
  human release-authorization records;
  no claim to provide a general-purpose agent harness or universal runtime adapters.
- Bound task-packet generation to trusted initialization/classification evidence
  and tightened release-manifest, verification, and audit-lineage checks without
  adding a historical-task migration path.
- Consolidated operator documentation for the inherited core platform, release
  checks, preserved state, and bounded pilot evidence.

### Fixed

- Allowed a zero-finding independent review to recommend `INTEGRATING` when no
  current blocker exists, while retaining fix-required and blocker-closure rules.
- Hardened preview/verification paths against unsupported transitions, snapshot
  drift, and JSON boolean/numeric type confusion through regression coverage.

### Scope and validation boundary

- Windows Server 2022 / Python 3.13; local, single-user, human-supervised core.
- Existing FTIC source-change closeout and integrated project-assurance dogfood
  evidence remain frozen outside the public source archive.
- Bounded execution remains implemented, unqualified, and disabled by default.
  P4/P5 qualification, autonomous model execution, new adapters, live trading,
  broker access, automatic deployment, and automatic release remain out of scope.
- This candidate-preparation gate changes release documentation only; it adds no
  product feature, schema, authority layer, or dependency.

## [1.0.0] - 2026-08-26

### Added

- Windows Server 2022/Python 3.13 v1.0 core-only release-readiness validation.
- Read-only CLI inspection of pending human decisions for supervised operation.
- Windows/Python 3.13 v0.1 release-readiness validation and a deterministic source ZIP builder.
- Release-candidate CLI binding for one or more hash-verified build artifacts using the existing manifest schema.
- Approved ACGPS v0.1 design baseline.
- Human/model decision boundaries.
- Risk, workflow, skill-routing, and model-routing policies.
- FTIC dogfood plan.
- Codex kickoff prompt and role contracts.
- WP-1 versioned contract validation package with runtime fixtures.
- Step2 design review index and supporting design definition documents.
- Declared Python dependency file for PyYAML.

### Changed

- The v1.0 release claim is limited to the human-supervised core control plane;
  bounded-executor P4/P5 qualification and autonomous model execution remain deferred.
- The `release` project check now validates readiness without publishing or claiming release authorization.
- The frozen test-applicability universe includes the release-readiness regression tests; Linux release qualification remains backlog.
- Runtime contract validation now enforces nested list item types, dictionary value types, real RFC 3339 UTC timestamps, safe path items, task-state pending-decision invariants, verified-evidence requirements, review-closure evidence requirements, and RC_READY evidence paths.
- Specification content digest now covers controlled source/specification files and ignores runtime caches and generated review packages.
- Project state, verification report, and package manifest are refreshed for the R03 design review baseline.

### Review

- R02 external design review findings were triaged in the private development record, which is not included in the clean public source candidate.
- P2 findings are retained as backlog and are not blockers for the revised design review submission.
