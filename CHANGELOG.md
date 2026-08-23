# Changelog

## [Unreleased]

### Added

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

- The `release` project check now validates readiness without publishing or claiming release authorization.
- The frozen test-applicability universe includes the release-readiness regression tests; Linux release qualification remains backlog.
- Runtime contract validation now enforces nested list item types, dictionary value types, real RFC 3339 UTC timestamps, safe path items, task-state pending-decision invariants, verified-evidence requirements, review-closure evidence requirements, and RC_READY evidence paths.
- Specification content digest now covers controlled source/specification files and ignores runtime caches and generated review packages.
- Project state, verification report, and package manifest are refreshed for the R03 design review baseline.

### Review

- R02 external design review findings were triaged in `reviews/responses/DESIGN_FINDING_RESPONSE_ACGPS-v0.1-wp1-WP1-R02-20260722T015056Z.md`.
- P2 findings are retained as backlog and are not blockers for the revised design review submission.
