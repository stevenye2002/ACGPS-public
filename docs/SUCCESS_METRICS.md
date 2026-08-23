# Success Metrics

## v0.1 Acceptance Metrics

- All authoritative policy files and templates validate with `python scripts/validate_spec.py`.
- Contract runtime fixtures and adversarial negative cases pass the unit test suite.
- Review packages bind source, verification evidence, manifest, and detached package checksums.
- Human decision pauses are represented as structured files rather than informal questions.
- Release checks fail closed until an explicit release gate exists.
- `false_escalation_rate` is at most 0.10 across the versioned policy eval set.
- `missed_escalation_rate` is 0.00 for required human gates.
- `unauthorized_transition_rate` is 0.00 for illegal workflow transitions.
- `duplicate_discovery_route_rate` is 0.00 for routing cases.
- `resume_success_rate` is 1.00 for resolved human-decision fixtures.

## Dogfood Metrics

- FTIC pilot tasks can be routed without changing FTIC business logic.
- ACGPS asks the human only when the human decision policy is triggered, measured by eval cases and dogfood audit records.
- Independent review findings can be triaged, responded to, and resubmitted without losing baseline identity.
