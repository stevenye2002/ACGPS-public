# Domain Context

ACGPS is an engineering control plane for complex software work. Its domain is not a managed product's business logic; it coordinates planning, implementation, review, verification, evidence capture, and human decision gates around those projects.

The v0.1 target environment is a single local workspace operated through CLI commands and file-backed records. The first dogfood project is FTIC, but ACGPS core rules must remain reusable and must not encode FTIC-specific intelligence, forecasting, reporting, investment, or story logic.

The project assumes a human owner retains authority over goals, value choices, risk acceptance, external actions, and release. Automation may progress only through workflow transitions that have evidence or an explicit human decision record.
