# Data Source Strategy

ACGPS v0.1 uses repository files as its source of truth. Authoritative design, policy, state, templates, review records, and test fixtures live in versioned paths.

Generated review packages are delivery artifacts, not alternate sources of truth. The source baseline for a review round is identified by Git commit when a repository is available, and by package manifests and detached SHA-256 checksums for generated archives.

Managed-project business data remains outside ACGPS core. The FTIC dogfood pilot may reference FTIC paths as evidence, but ACGPS must not reinterpret or mutate FTIC business logic.
