# Test And Evaluation Strategy

## Required Checks

- `python scripts/validate_spec.py` validates required design files, YAML policy parsing, workflow transition references, and placeholder hygiene.
- `python -m unittest discover -s tests -v` validates contracts, policy consistency, review-state single source rules, and release fail-closed behavior.
- `python scripts/check.py full` runs the project-defined full local check.
- `python scripts/check.py release` is expected to fail closed in v0.1 because automatic production release is out of scope.
- `config/policy_eval_cases.yaml` defines expected risk, skill, model-role, Human Gate, and allowed-transition outcomes for the policy engine.

## Evidence Rules

Verification records must include actual checks, requirements checked, command summaries, and output paths. A `VERIFIED` recommendation cannot be issued with zero checks or unchecked requirements.

Review packages must include enough context for independent assessment: requirements, source identity, finding responses, verification evidence, manifest, and detached archive checksum.

Review package evidence is split into three non-circular hash domains: `source_tree`, `evidence_set`, and `review_bundle`. The rules are defined in `docs/REVIEW_ARTIFACT_PROTOCOL.md`.

## Policy And Agent Eval Scope

- Policy evals measure `false_escalation_rate`, `missed_escalation_rate`, `unauthorized_transition_rate`, `duplicate_discovery_route_rate`, reproducibility, and `resume_success_rate`.
- Agent packet evals check role isolation, required constraints, evidence sufficiency, prompt-injection labeling, and secret/path exclusion.
- WP-2 cannot close until its policy eval cases pass against deterministic implementation output.
