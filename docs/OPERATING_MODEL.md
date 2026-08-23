# Operating Model

ACGPS operates as a staged local workflow.

1. The human owner approves intent and scope.
2. The Planner converts approved intent into a bounded plan.
3. The Coder implements scoped work using tests and local evidence.
4. The Reviewer independently evaluates the baseline and findings.
5. The Verifier checks actual evidence before any completion claim or transition.
6. The workflow controller records authorized transitions and audit evidence.
7. The human owner authorizes release or any external, irreversible, costly, or risk-bearing action.

Human questions are not casual prompts. When policy requires human judgment, ACGPS creates a structured decision request under `decisions/pending/` and pauses in `WAITING_HUMAN`.
