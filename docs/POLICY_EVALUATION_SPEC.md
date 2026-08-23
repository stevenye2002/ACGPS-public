# Policy Evaluation Specification

## Purpose

WP-2 evaluates versioned policy inputs and returns deterministic gate, routing, and transition guidance. It does not persist workflow state, create human decision records, execute CLI commands, or release software.

## Input Contract

The authoritative input contract is `policy_evaluation_input` version 1. Its `input` object contains:

- `current_state`: one state from `config/workflow_policy.yaml`.
- `risk_triggers`: risk trigger IDs from `config/risk_policy.yaml`, plus selected-profile-only trigger IDs explicitly registered in that profile's `risk_overrides`.
- `human_triggers`: human-decision trigger IDs from `config/human_decision_policy.yaml`.
- `task_attributes`: bounded string attributes from `config/policy_routing_features.yaml`, used only for deterministic routing.
- `project_profile_id`: a known profile ID or null.

Unknown risk trigger IDs, unknown human trigger IDs, unknown or invalid project profile IDs, unknown routing attribute keys or values, duplicate set-like input members, unknown schema version, type confusion, missing required policy, malformed YAML, and duplicate key input must fail closed with an actionable issue list and no partial decision output.

## Output Contract

The authoritative output contract is `policy_evaluation_result` version 1. Its `result` object contains:

- `risk_level`: enforced highest applicable level.
- `human_gate`: true when a human trigger or R3 production/external condition requires a pause.
- `required_human_triggers`: matched human-decision triggers.
- `required_skills`: canonical skill IDs from `config/skill_routing.yaml`.
- `model_roles`: canonical role capability IDs from `config/model_routing.yaml`.
- `mandatory_gates`: gates attached to the enforced risk level and policy decision.
- `legal_transitions`: workflow targets declared for the current state before gate authorization.
- `authorized_transitions`: legal targets the controller may take without an unresolved human decision.
- `provenance`: policy paths that explain the decision.
- `fail_closed`: true only when evaluation rejected the input without emitting partial transition authorization.
- `decision_emitted`: false when `fail_closed` is true; true only when all output fields are complete.
- `error_code`: stable machine-readable error code or null.
- `issues`: stable issue objects with `code`, `path`, and `message`.

Fail-closed results use a canonical rejection envelope: `decision_emitted=false`, `fail_closed=true`, `risk_level=R3`, `human_gate=true`, empty executable output fields, a registered `error_code`, and one or more issues whose `code` values match the top-level error. Policy error codes are defined by a single versioned registry in `acgps/policy_errors.py`; contracts, executable specification checks, fixtures, and documentation must not maintain independent drifting copies.

## Merge And Precedence Rules

Precedence is deterministic:

1. Global policies provide the base vocabulary and default level.
2. Project profiles may bind recognized profile-specific triggers through `risk_overrides` and may raise risk.
3. Project profiles may not silently lower risk, delete global gates, bypass human triggers, remove required verification, or enable production release.
4. Same-priority conflicting values fail closed unless the field explicitly uses union semantics.
5. List-valued gates, skills, triggers, and provenance use deterministic preserve-first union semantics from global policy, profile override, routing, model, then workflow source order.
6. Scalar fields such as enforced risk level use highest-risk-wins semantics.
7. Unknown keys, unknown versions, duplicate YAML keys, missing policy files, and cross-file ID conflicts fail closed.

Profile override provenance must name the source file and key. If the evaluator cannot produce unambiguous provenance, it must fail closed.

Human-gated results preserve the legal workflow targets but only authorize `WAITING_HUMAN` and, where legal for the current state, `ABANDONED`. The controller must not interpret `legal_transitions` as authorization.

### Field-Level Profile Merge Contract

| Field | Merge rule | Profile authority |
| --- | --- | --- |
| `profile_id` | Unique key across discovered profiles | Duplicate profile IDs fail closed. |
| `required_files` | Profile-specific map; no global merge | Unknown or unsafe paths fail validation. |
| `critical_surfaces` | Deterministic union sorted by policy declaration order | May add surfaces, may not remove global controls. |
| `risk_overrides` | Per-trigger highest-risk-wins | May register profile-only triggers and may raise global triggers; may not lower global risk. |
| `pilot_restrictions` | Deterministic union | May add restrictions, may not remove restrictions. |
| `commands` | Profile-specific map | Used by later command orchestration only; WP-2 does not execute commands. |

Profile-only trigger registration must be explicit in the selected profile's `risk_overrides` and covered by the eval catalog or runtime semantic tests. Profile discovery records must retain the real source path, and profile-only trigger provenance must use that source path and key, such as `project_profiles/<profile-file>.yaml:risk_overrides.<trigger>`. Unknown profile triggers, unsupported profile schema versions, duplicate profile IDs, unexpected profile fields, invalid `risk_overrides` shape or values, attempted downgrades, unsafe or missing `required_files`, same-priority conflicts, and file-order ambiguity fail closed with stable issue paths.

### Routing Vocabulary

`config/policy_routing_features.yaml` is the versioned routing vocabulary. It defines allowed task-attribute keys and values, risk-derived feature tokens, skill rule features, model role rules, and canonical ordering for set-like inputs. Implementations must evaluate routing from this table rather than hard-coding unversioned task-attribute interpretations. Test harness controls such as fixture selection are not public task attributes and must not appear in `PolicyEvaluationInput`.

## Eval Coverage

`config/policy_eval_cases.yaml` is a versioned eval catalog. It must include positive, human-gate, UI-route, production-boundary, unknown-ID, actual-raise, deterministic replay, malformed-input, duplicate-discovery, unknown-version, attempted-downgrade, conflict, missing-policy, order-perturbation, and type-confusion coverage before WP-2 implementation can be accepted. Negative fixture cases may use a case-level `fixture_id` test-harness field outside `input`; that field is not part of the public `PolicyEvaluationInput` contract.

The shipped executable checks define the oracle shape. `scripts/run_policy_eval_fixtures.py` exercises the shared loader and evaluator against the versioned fixture catalog, while `python scripts/check.py full` covers deterministic replay and mutations to risk level, human gate, skills, roles, gates, transitions, fail-closed errors, issues, and provenance. Set-like input order must not change canonical result bytes; duplicate set-like input members are rejected rather than silently deduplicated.

## Security Controls

Policy files and project profiles are untrusted structured input until validated. WP-2 must reject duplicate YAML keys, unknown IDs, unknown schema versions, type confusion, resource-expanding aliases, conflicting rules, override downgrade attempts, and malformed input.

The evaluator must produce registered stable error codes, stable issue paths, and no partial decision output for rejected inputs. Concrete adversarial fixtures live under `tests/fixtures/policy_eval/`; `scripts/run_policy_eval_fixtures.py` is the independent fixture runner used before WP-2 implementation authorization. The runner uses fixture directories as harness input, executes the shared loader, schema, profile-discovery, merge, conflict, and error-construction phases in a fixed reference order, and rejects coordinated tampering of expected error records.
