# Glossary

- ACGPS: AI Coding Good Practice System, the reusable engineering control plane built by this repository.
- Control plane: The local workflow, policy, evidence, and review layer that governs task progression.
- Managed project: A project coordinated by ACGPS, such as FTIC during the first dogfood pilot.
- Human owner: The person who owns product intent, value trade-offs, risk acceptance, irreversible choices, external actions, and release authorization.
- Workflow controller: The authority that evaluates evidence and authorizes state transitions.
- Planner: The role that turns approved intent into architecture and an implementation plan.
- Coder: The role that implements scoped changes under a task contract.
- Reviewer: The independent role that identifies defects, risks, and missing tests.
- Verifier: The independent role that checks evidence before a transition or delivery claim.
- Human decision request: A structured pause record stored under `decisions/pending/` when policy requires human judgment.
- Review round: An immutable bundle containing baseline, requirements, findings, responses, and verification evidence for independent review.
