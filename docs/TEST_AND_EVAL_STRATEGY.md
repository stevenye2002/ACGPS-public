# Test And Evaluation Strategy

## Required Checks

- `python -m unittest discover -s tests -v` validates contracts, policy consistency, review-state single source rules, and release fail-closed behavior.
- `python scripts/check.py full` runs the project-defined full local check.
- `python scripts/check.py release` validates the deterministic v1.0 core source boundary without publishing or authorizing production release.
- `config/policy_eval_cases.yaml` defines expected risk, skill, model-role, Human Gate, and allowed-transition outcomes for the policy engine.

## Bounded Windows Executor Profiles

The bounded executor accepts only the closed platform-profile set defined by the
`coding_execution_record` contract. The supported profiles are Windows 11 x64 and
Windows Server 2022 x64, each using NTFS, Python 3.13, the native elevated sandbox,
and a private desktop.

Selecting a profile does not qualify the host. Each exact OS build and executor
artifact must independently pass P0-P6 before model execution. Qualification must
include the negative write, agent-tool network, prohibited-surface, unallowlisted
process, timeout/descendant, secret-environment, and unauthorized-patch cases. No
evidence from one profile carries over to the other.

For v1.0 core, the bounded executor is implemented but unqualified and disabled
by default. P4/P5 qualification and every autonomous model launch are deferred;
they are not acceptance criteria for the human-supervised core release.

The Windows Server 2022 profile covers bounded development execution only. It does
not authorize production deployment, live trading, access to broker credentials, or
co-location with a live MT4/MT5 execution boundary.

The v1.0 core release check independently requires Windows Server 2022 and
Python 3.13, but it does not convert that core platform check into executor
qualification.

## Evidence Rules

Verification records must include actual checks, requirements checked, command summaries, and output paths. A `VERIFIED` recommendation cannot be issued with zero checks or unchecked requirements.

Review packages must include enough context for independent assessment: requirements, source identity, finding responses, verification evidence, manifest, and detached archive checksum.

Review package evidence is split into three non-circular hash domains: `source_tree`, `evidence_set`, and `review_bundle`. The rules are defined in `docs/REVIEW_ARTIFACT_PROTOCOL.md`.

## Policy And Agent Eval Scope

- Policy evals measure `false_escalation_rate`, `missed_escalation_rate`, `unauthorized_transition_rate`, `duplicate_discovery_route_rate`, reproducibility, and `resume_success_rate`.
- Agent packet evals check role isolation, required constraints, evidence sufficiency, prompt-injection labeling, and secret/path exclusion.
- WP-2 cannot close until its policy eval cases pass against deterministic implementation output.
