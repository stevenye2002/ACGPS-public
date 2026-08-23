# Role and Decision Matrix

## Human Product & Risk Owner

Owns:

- project goal, target users, product value, priorities, and success criteria;
- domain corrections that cannot be derived from authoritative sources;
- risk acceptance and ethical, legal, privacy, financial, or brand trade-offs;
- irreversible choices and production release authorization.

Does not routinely decide internal file structure, ordinary tests, reversible implementation details, or fixes already required by an approved specification.

## Workflow Controller

Owns:

- current lifecycle state;
- policy evaluation;
- role and skill routing;
- evidence requirements;
- whether a transition may occur;
- creation of human-decision requests;
- audit records.

It does not define product value or accept risk.

## Planner / Architect

Owns:

- requirements clarification;
- alternatives and trade-offs;
- specifications, architecture, ADRs, acceptance criteria, and work-package decomposition;
- test and release strategy recommendations.

It recommends but does not accept human-owned risks.

## Coding Agent

Owns:

- bounded implementation;
- tests and documentation required by the task;
- focused checks and implementation evidence.

It may choose reversible internal details consistent with the approved plan. It may not expand scope, alter approved product meaning, self-approve, or release.

## Independent Reviewer

Owns:

- specification compliance;
- defect discovery;
- code quality, compatibility, security, test-quality, and overengineering findings;
- structured dispositions for review findings.

It does not silently change the approved specification.

## Verifier / Release Agent

Owns:

- inspection of fresh test, build, schema, security, browser, artifact, hash, and installation evidence;
- release-candidate evidence packaging;
- reporting actual readiness.

It cannot authorize production release.

## Decision authority table

| Decision | Human | Controller | Planner | Coder | Reviewer | Verifier |
|---|---|---|---|---|---|---|
| Product goal/value | Approves | Records | Recommends | No | Challenges | No |
| Scope and non-goals | Approves material scope | Enforces | Defines | Cannot expand | Checks | Checks evidence |
| Internal implementation | Usually no | Bounds | Plans | Chooses | Reviews | Verifies |
| Public contract break | Approves | Blocks until resolved | Recommends | No | Assesses | Verifies |
| Risk acceptance | Approves | Records/blocks | Advises | No | Surfaces | No |
| Skill/model routing | Defines policy | Decides per policy | Advises | No | Checks | No |
| State transition | No | Authorizes | Supplies artifacts | Supplies artifacts | Supplies findings | Supplies evidence |
| RC readiness | Accepts residual risk | Gates | Recommends | No | Recommends | Proves evidence |
| Production release | Authorizes | Executes authorized path | No | No | No | Confirms package |
