# Human Decision Policy

## Principle

Humans decide values, risk, irreversible consequences, and external authorization. Models and deterministic tools decide reversible implementation details and verifiable facts.

## Mandatory human-decision triggers

### H1 — Product intent or value ambiguity

Use when materially different interpretations lead to different users, outcomes, priorities, or product meaning.

### H2 — Irreversible or costly choice

Use for destructive migration, permanent compatibility break, major vendor lock-in, substantial new cost, or choices with no credible rollback.

### H3 — Risk acceptance

Use for known security, privacy, legal, medical, financial, investment, ethical, or audit risk that cannot be eliminated within approved scope.

### H4 — Human experience or normative trade-off

Use for brand, creative direction, commercial-versus-artistic balance, user-experience alternatives, or other value choices not mechanically provable.

### H5 — External or production action

Use for production deployment, external communication, real payment, trading, public publication, production data modification, or third-party commitments.

## Do not escalate

Do not ask the human when:

- the repository, approved specification, tests, or policies answer the question;
- the decision is local, reversible, and bounded;
- the plan already authorizes the choice;
- an independent review identifies an objective defect;
- a validation command can determine the fact.

## Required request format

Use `templates/HUMAN_DECISION_REQUEST.yaml`. Every request must include:

- reason for escalation;
- one precise question;
- two or more concrete options when possible;
- recommended option and rationale;
- consequences and reversibility;
- evidence paths;
- default action without a response, normally `PAUSE`.
