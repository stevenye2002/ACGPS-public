# Skill Routing Policy

## General rule

Use skills by trigger. Do not force every skill on every task. Avoid duplicate discovery or review workflows that ask the same questions twice.

## Primary discovery route

Select exactly one primary discovery method:

- Deep domain ambiguity or new complex project: `grill-with-docs` or equivalent evidence-backed interview.
- New feature, behavior, or architecture with normal domain clarity: Superpowers brainstorming.
- Clear low-risk task: concise specification without full interview.

Once discovery is recorded, downstream skills read the artifact instead of repeating the interview.

## Superpowers routing

| Skill | Mandatory trigger |
|---|---|
| brainstorming | New project, new capability, material behavior or architecture change when no approved spec exists |
| writing-plans | Multi-step, multi-file, integration, or high-risk implementation |
| test-driven-development | Bug fixes and behavior changes unless a documented exception applies |
| systematic-debugging | Unexpected failure, failing test, regression, or unclear behavior |
| using-git-worktrees | Formal feature work, parallel tasks, or review-isolated implementation |
| subagent-driven-development | Two or more sufficiently independent planned tasks in one execution cycle |
| executing-plans | Approved plan executed in a controlled sequential session |
| requesting-code-review | Before integration, formal milestone, RC, or high-risk closure |
| verification-before-completion | Every completion, passing, fixed, merge, or release-readiness claim |
| finishing-a-development-branch | After implementation and final review are complete |

## Figma and product-design routing

Mandatory when the task creates or materially changes:

- a user interface;
- a critical user journey;
- responsive behavior;
- visual design system or reusable components;
- high-fidelity product experience.

Not mandatory for backend, CLI, data pipeline, research engine, or internal API tasks without a user interface.

For UI work, require design context before implementation and browser/design QA after implementation.

## Specialist skills

Project profiles may require specialist skills such as security review, financial model audit, data-quality validation, forecast integrity, research integrity, browser QA, or creative-story review.

## Exceptions

Exceptions must be explicit in the task contract, include rationale, and never exempt fresh verification before completion.
