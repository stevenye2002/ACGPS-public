# External Resource Strategy

ACGPS v0.1 avoids external side effects by default. It may produce prompts, task packets, review bundles, and local evidence, but it does not send production email, deploy to production, publish public artifacts, place transactions, or modify managed-project production data.

External tools and skills are trigger-based. Figma is required only for UI or UX work. Browser, security, data, or project-specific skills are used only when their routing conditions apply.

Any external action that affects production, public visibility, real users, financial outcomes, legal exposure, privacy exposure, or vendor lock-in requires a structured human decision record before execution.
