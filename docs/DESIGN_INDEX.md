# Design Index

This index maps the public Step2 design materials to the ACGPS v0.1 baseline.
Private work-package records, dynamic project state, review history, and full
review-package tooling are intentionally outside the clean public source
candidate.

| Step2 material | Primary source |
| --- | --- |
| Domain context | `docs/DOMAIN_CONTEXT.md` |
| Glossary | `docs/GLOSSARY.md` |
| Product specification | `docs/PRODUCT_SPEC.md` |
| Use cases | `docs/USE_CASES.md` |
| Success metrics | `docs/SUCCESS_METRICS.md` |
| Architecture | `docs/ARCHITECTURE.md`, `docs/SYSTEM_DESIGN.md` |
| External resource strategy | `docs/EXTERNAL_RESOURCE_STRATEGY.md` |
| Data source strategy | `docs/DATA_SOURCE_STRATEGY.md` |
| Security and privacy | `docs/SECURITY_AND_PRIVACY.md` |
| Test and evaluation strategy | `docs/TEST_AND_EVAL_STRATEGY.md` |
| Review artifact protocol | `docs/REVIEW_ARTIFACT_PROTOCOL.md` |
| Operating model | `docs/OPERATING_MODEL.md` |
| Requirement traceability | `docs/ACCEPTANCE_CRITERIA.md`, `docs/SYSTEM_DESIGN.md` |
| Work package readiness | Private development records; not included in the clean public source candidate. |
| Threat, recovery, and control model | `docs/THREAT_CONTROL_MATRIX.md` |

## Traceability

- Product intent and non-goals: `docs/PROJECT_GOAL.md`, `docs/MVP_SCOPE.md`
- Authority boundaries: `docs/ROLE_DECISION_MATRIX.md`, `docs/HUMAN_DECISION_POLICY.md`
- Workflow contract: `docs/WORKFLOW_STATE_MACHINE.md`, `config/workflow_policy.yaml`
- Risk and routing: `docs/RISK_CLASSIFICATION.md`, `docs/SKILL_ROUTING_POLICY.md`, `docs/MODEL_ROUTING_POLICY.md`
- Work plan and current state: private development records; not included in the clean public source candidate.
- Acceptance evidence: `docs/ACCEPTANCE_CRITERIA.md`, `tests/`
- Policy eval fixtures: `config/policy_eval_cases.yaml`
- Public review and archive surfaces: `acgps/review_adapter.py`, `scripts/build_mvp_source_archive.py`; the full private review-package toolchain is not included.
