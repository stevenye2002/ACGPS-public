# Review Package Builder

This document records the v0.1 private review-package builder contract. The
clean public source candidate intentionally omits that builder, its publication
tooling, platform-evidence records, and private review history; this document is
not a public command reference. The shipped `acgps/review_adapter.py` provides
the narrower release-candidate review-evidence boundary, and
`scripts/build_mvp_source_archive.py` builds deterministic public source
archives. Neither implements the complete builder described below. In the
private workflow, the builder orchestrates committed-source export, evidence
construction, bundle construction, protocol verification, create-once
publication, and the final ready-record commit point. A successful build is not
an independent review, semantic acceptance, implementation authorization, or
release decision.

## Result and failure contract

The builder emits one closed-schema JSON result to stdout. A successful result
uses `build_status: SUCCEEDED`, `failure_stage: null`, `error_code: null`, and
`artifact_set_committed: true`. Failures return `build_status: FAILED`, a stable
stage/error pair, diagnostics status, and `artifact_set_committed: false`.

Top-level failure stages are `PREFLIGHT`, `SOURCE_EXPORT`, `EVIDENCE_BUILD`,
`BUNDLE_BUILD`, `VERIFICATION`, `PUBLICATION`, and `CLEANUP`. Publication event
names may also identify the exact injected/observed stage. Stable builder errors
include `PREFLIGHT_FAILED`, `SOURCE_EXPORT_FAILED`, `EVIDENCE_BUILD_FAILED`,
`BUNDLE_BUILD_FAILED`, `FINAL_CANDIDATE_VERIFICATION_FAILED`,
`ARTIFACT_SET_VERIFICATION_FAILED`, `PUBLICATION_FAILED`, `CLEANUP_FAILED`, and
`INJECTED_PUBLICATION_STAGE_FAILURE`. Inventory and filesystem errors retain the
more specific protocol codes documented in `REVIEW_ARTIFACT_PROTOCOL.md`.

Failed or orphaned final artifacts are quarantined with a recovery journal.
Diagnostics are bounded to 100 MiB, at most five retained failures, fourteen
days of retention, and one MiB per child log; source archives are not retained
by the diagnostics policy.

## Final publication ordering

The following order is the enforced final event sequence:

1. `CANDIDATE_BYTES_FROZEN`
2. `FINAL_CANDIDATE_VERIFIED`
3. `WINDOWS_SIDECAR_VERIFIED`
4. `LINUX_SIDECAR_VERIFIED`
5. `PLATFORM_MATRIX_VERIFIED`
6. `BUILD_RECORD_GENERATED`
7. `DETACHED_SHA_GENERATED`
8. `CANDIDATE_ZIP_PUBLISHED`
9. `WINDOWS_SIDECAR_PUBLISHED`
10. `LINUX_SIDECAR_PUBLISHED`
11. `PLATFORM_MATRIX_PUBLISHED`
12. `BUILD_RECORD_PUBLISHED`
13. `DETACHED_SHA_PUBLISHED`
14. `ARTIFACT_SET_VERIFIED`
15. `READY_CREATED`

The candidate is protocol-verified before final publication. Platform sidecars
and their matrix are verified before they are published. After all create-once
artifacts are present, the builder verifies a private mirror of the prospective
artifact set, rehashes the published ZIP, revalidates both platform sidecars,
the matrix, the immutable build record, and all source-equivalence bindings.
Only then is the ready record atomically created.

## Commit model

The sole v0.1 artifact-set commit point is:

```text
<package>.ready.json
```

Before this atomic write, the ZIP, Windows sidecar, Linux sidecar, platform
matrix, detached SHA-256, and immutable build record are uncommitted candidates.
If any verification or publication stage fails, no ready record is written and
the result remains uncommitted. The ready record binds names and SHA-256 values
for the ZIP, checksum file, build record, both sidecars, platform matrix, source
equivalence identities/counts, and `artifact_set_digest`.

The ready record also declares its local publication root as
`NON_AUTHORITATIVE_LOCAL_DIAGNOSTIC`. The artifact identity comes from the
recorded hashes and logical round, not from an absolute local path.

## Platform evidence and matrix

Each package candidate first gets create-once Windows and Linux Task 6 minimal
sidecars (`PLATFORM_EVIDENCE_SIDECAR_V1`) and a
`TASK6_MINIMAL_PLATFORM_MATRIX_V1`. These records bind platform and candidate
SHA-256, declare `TASK8_PENDING`, and are revalidated during artifact-set
verification. They do not claim runner qualification or test partitions.

Task 8 separately accepts full external `REVIEW_PLATFORM_EVIDENCE_V1` records
only through the closed external context and sidecar schemas. Those records bind
source identity, inventory digest, applicability authority, environment facts,
command argv, and exact test partitions. Their qualified matrix binds both full
platform records to the same candidate/source identity and requires the frozen
cross-platform required-test union to be complete. Candidate mutation, identity
drift, incomplete discovery, unexpected skips, unqualified runners, or source/
applicability mismatch fails closed.

## Authorization boundary

Build-result and ready-record schemas require:

```text
authorization_granted = false
acceptance_signal_emitted = false
architecture_signal_issued = false
implementation_accepted = false
automatic_next_authorized = false
```

The ready record commits an artifact set, not a workflow transition. Independent
review and Human/Controller records alone can accept it or authorize a successor.

## Path, locking, and physical names

The builder uses a per-identity lock and a short private build root. Every write
must be present in the frozen `PackagePathPlanV1`; path overages and unplanned
writers fail closed. Publication uses create-once writes and refuses a conflicting
existing identity. The physical artifact form is:

```text
RPKG-<work-package-id>-<round-short>-<commit8>-<UTC>.zip
```

The full logical review round remains in the result, build record, ready record,
and bundle metadata rather than being repeated in every physical path component.
