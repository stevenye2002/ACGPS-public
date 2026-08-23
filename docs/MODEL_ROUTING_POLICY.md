# Model Routing Policy

## Principle

Use role separation and task fit, not maximum model capability for every action. Resource abundance permits stronger independent judgment but does not justify context waste or self-review.

## Recommended routing

- Product discovery, architecture, difficult planning, and final branch review: strongest available reasoning model.
- Research-heavy evidence synthesis: strongest model with source tools.
- Multi-file integration coding: strong coding model.
- Clear, bounded, mechanical implementation: efficient coding model.
- Task review: independent model sized to risk; never the same active context as the Coder.
- Final RC review: strongest independent model.
- Verification: deterministic tools first; model summarizes evidence but does not replace it.

## Escalation

Escalate to a stronger model when:

- the task spans multiple contracts or subsystems;
- implementation reports `BLOCKED` due to reasoning difficulty;
- reviewers disagree on a material issue;
- security, concurrency, temporal integrity, or financial logic is involved;
- remediation loops repeat without converging.

## Context control

Each dispatched agent receives only:

- its role contract;
- the task or finding;
- binding project constraints;
- relevant file paths and interfaces;
- required evidence.

Do not paste accumulated session history into every agent prompt.
