# Review Artifact Protocol

This document describes the implemented v1 review-artifact protocol. It is a
public contract for reproducibility and fail-closed verification; it does not
grant review acceptance, implementation authority, or an automatic next step.

## Hash domains and source authority

`hash_protocol_version` is integer `1`. SHA-256 is applied to raw file bytes or
canonical JSON, depending on the record. Unknown, missing, conflicting, Boolean,
or otherwise invalid protocol discriminators fail closed.

The source domain is a committed Git object identified by `source_commit` and
`source_tree`. `CanonicalSourceInventoryV1` is the closed, ordered inventory of
that object and contains:

- `schema_version`
- `source_commit`
- `source_tree`
- `git_object_format`
- integer `path_policy_version`
- `file_count`
- `files`
- `inventory_digest`

Rows are sorted by `row.path.encode("utf-8")`. The `inventory_digest` is
lowercase hexadecimal SHA-256 over the UTF-8 bytes of this complete canonical
JSON object:

```python
json.dumps(
    {
        "schema_version": 1,
        "source_commit": source_commit,
        "source_tree": source_tree,
        "git_object_format": git_object_format,
        "path_policy_version": 1,
        "file_count": len(files),
        "files": [
            {
                "path": row.path,
                "uncompressed_size": row.uncompressed_size,
                "sha256": row.sha256,
                "git_mode": row.git_mode,
            }
            for row in sorted(files, key=lambda row: row.path.encode("utf-8"))
        ],
        "inventory_digest": None,
    },
    sort_keys=True,
    separators=(",", ":"),
    ensure_ascii=False,
).encode("utf-8")
```

The `inventory_digest` is represented as JSON `null` during hashing. Its digest
domain binds the source identity, path policy, `file_count`, and every ordered
file row, including each row's `path`, `uncompressed_size`, `sha256`, and
`git_mode`. Row-only digests, raw source-archive SHA-256, and packaged-source
or content-view digests occupy separate domains and are not valid substitutes
for `inventory_digest`.

The canonical `SOURCE_MANIFEST.v1` is a projection of that inventory plus the
source archive binding. `source_archive_sha256` belongs to the manifest
envelope, not to `CanonicalSourceInventoryV1`.

The final candidate must have four equal source views: the canonical inventory,
`source_baseline.zip`, packaged `source/`, and `SOURCE_MANIFEST.v1`. The builder
freezes candidate bytes, verifies these views, and records their digests and
counts before any ready record can be created. The first-adoption comparator
also compares the canonical view with `git ls-tree` and `git cat-file` for the
frozen commit.

The `evidence_set` domain binds verification generated from that exact source
identity. The `review_bundle` domain binds the submitted source, evidence,
review context, request, manifests, prior findings, and finding responses.

## Path and filesystem policy

Path policy version `1` is a hard, fail-closed contract. It enforces:

- component length at most 80 UTF-16 code units;
- archive-relative path length at most 180 UTF-16 code units;
- directory depth at most 12;
- final absolute path length at most 220 UTF-16 code units;
- 36 UTF-16 units reserved for temporary suffixes within the 259-unit legacy
  Windows boundary;
- rejection of absolute members, parent traversal, unsafe ZIP names,
  Windows-invalid characters, reserved device names, case-insensitive
  collisions, Unicode-normalization collisions, duplicates, links, and reparse
  points.

These limits are not advisory. An overage raises `PackagePreflightError` with
code `PATH_BUDGET_EXCEEDED`. All writer destinations and temporary siblings must
belong to `PackagePathPlanV1`; any undeclared writer path fails with
`UNPLANNED_WRITER_PATH`. Private roots and publication roots are anchored,
non-linked directories whose identity is rechecked across the lifecycle.

The provider-stability pass reads every source entry in frozen order, records
all detected mismatches, and then raises
`SOURCE_PROVIDER_STABILITY_DIVERGENCE`. Source disappearance or mutation,
archive drift, source-view divergence, identity drift, unsafe cleanup, and
linked/reparse substitutions fail closed; they are never converted into a
successful build.

Stable error families include:

- `INVALID_SOURCE_INVENTORY`
- `PRIVATE_BUILD_ROOT_INVALID`
- `PATH_BUDGET_EXCEEDED`
- `UNPLANNED_WRITER_PATH`
- `SOURCE_ARCHIVE_DRIFT`
- `SOURCE_PROVIDER_STABILITY_DIVERGENCE`
- `SOURCE_OUTPUT_DIVERGENCE`
- `SOURCE_OUTPUT_PUBLICATION_CLEANUP_FAILED`
- `SOURCE_OUTPUT_PUBLICATION_COMMITTED_CLEANUP_FAILED`
- `SOURCE_IDENTITY_MISMATCH`
- `PACKAGE_PROTOCOL_INVALID`
- `UNSUPPORTED_PROTOCOL_VERSION`
- `LEGACY_PACKAGE_INVALID`

## Protocol dispatch and compatibility

`scripts/review_protocol_dispatch.py` reads exactly one direct
`SOURCE_MANIFEST.json` and rejects duplicate JSON keys before dispatch.

- `manifest_type: SOURCE_MANIFEST`, integer `hash_protocol_version: 1`, and no
  `source_inventory_protocol_version` selects the immutable legacy v1 verifier.
- `manifest_type: SOURCE_MANIFEST.v1`, integer `hash_protocol_version: 1`, and
  no duplicate version field selects the canonical inventory v1 verifier.
- Any missing, unknown, mixed, conflicting, or unsupported discriminator fails
  with `PACKAGE_PROTOCOL_INVALID` or `UNSUPPORTED_PROTOCOL_VERSION`.

Legacy verification remains read-only compatibility logic. New canonical
packages do not silently fall back to it, and legacy output is not rewritten.

## Evidence, acceptance, and platform records

Evidence records bind exact command argv, environment facts, output, test
partitions, source identity, inventory digest, candidate SHA-256, applicability
manifest identity, and log encoding. Test counts must reconcile:

```text
passed + failures + errors + skipped = discovered
```

Failures and errors are forbidden in a successful platform record. The
historical WS-C Gate R02 applicability authority remains frozen at 443 tests.
The active integrated MVP applicability manifest is closed at 517 tests:
Windows must pass its 515 required tests and report exactly two approved skips;
Linux must pass its 509 required tests and report exactly eight approved skips.
Discovery must equal the active frozen universe, skip sets must match exactly,
required tests must pass, runner output must qualify, and the required union
across both platforms must be complete.

The package builder first publishes create-once Task 6 minimal sidecars with
record type `PLATFORM_EVIDENCE_SIDECAR_V1`. Each binds only the candidate
SHA-256, exact platform, deterministic record ID, and
`evidence_authority: TASK8_PENDING`; their minimal matrix identity is
`TASK6_MINIMAL_PLATFORM_MATRIX_V1`. These records are publication bindings, not
qualified runner evidence.

The later platform-evidence flow produces one full
`REVIEW_PLATFORM_EVIDENCE.v1.json` record for `windows` and one for `linux`.
Each binds the exact environment, command argv, discovered/passed/failure/error/
skip partitions, source commit/tree, inventory protocol and digest, candidate
SHA-256, test-universe digest, applicability-manifest path and SHA-256, required
tests, expected skips, and log encoding. The qualified platform matrix must bind
the same candidate and source identities, both full record hashes, and a
complete required-test union.

Acceptance evidence is generated from the frozen architecture authorities. Each
record binds the criterion or finding, requirement, behavioral assertions,
actual tests, changed files, evidence paths, platform limits, source identity,
submitter provenance, independent-review authority, Controller authority, and
authority-chain digest. It records evidence; it cannot self-verify or self-close
a finding.

## Manifest and state rules

`PACKAGE_MANIFEST.json` must not be tracked in the controlled source tree. Generated
manifests and ready/build records are outside the committed source domain to
avoid self-reference. `EVIDENCE_MANIFEST.json` binds verification outputs and
counts. `DESIGN_MANIFEST.json` binds the final review-bundle domain while
excluding itself and detached checksum files from its own digest.

All result and ready records keep these controls false:

```text
authorization_granted = false
acceptance_signal_emitted = false
automatic_next_authorized = false
```

Architecture and implementation acceptance fields also remain false unless a
later, separate Human/Controller transition records them. A successful build is
only an artifact-protocol result.

The executable contract is implemented by:

- `scripts/review_source_inventory.py`
- `scripts/build_review_evidence.py`
- `scripts/build_design_bundle.py`
- `scripts/build_review_package.py`
- `scripts/build_review_platform_matrix.py`
- `scripts/review_acceptance_evidence.py`
- `scripts/review_protocol_dispatch.py`
- `scripts/verify_review_bundle.py`
- `tests/test_review_source_inventory.py`
- `tests/test_review_artifact_pipeline.py`
