---
version: v1.0
METHODOLOGY_VERSION: v4.9
source: PBVI Phase 5 greenfield
frozen: true
---

# Claude.md — v1.0 · FROZEN · 2026-06-23

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-06-23 | Mahendra | Greenfield — Initial. Phase 4 gate passed. 22-invariant set post-Step-2b challenge. |

---

## Section 1 — System Intent

The SOC ingestion pipeline converts a raw GDS ZIP package into exactly one
standardised, PII-clean, credential-scrubbed, validated JSON record per
Application ID, aligned to Standard Schema v1.1, ready for DataLake write.
It does not perform real-time streaming, cross-client deduplication, PII vault
key management, CaseCenter write-back, or downstream analytics.
Success is a pipeline run against the 8-application sample that produces the
correct number of DataLake=Y records with zero raw PII, zero raw credentials,
complete lineage on every record, and a passing quarantine report.

---

## Section 2 — Hard Invariants

**CQ-001 (methodology-mandated — cannot be removed):**
Each function, method, or handler must have a single stateable purpose.
Conditional nesting exceeding two levels is a structural violation — refactor
before proceeding. This is never negotiable.

**IC-1:**
Credential scrub (`scrub_credentials()`) executes to completion on every file
in the manifest before any file is parsed, logged, or routed downstream.
The scrub implementation must use pattern-based detection (regex) — not
exact-string matching against known credential values. No connector payload
may be read, deserialised, or written to any log while a credential field in
that payload remains in its raw form. Connectors in scope: C161653
(HTTP Authorization header), C754889 (username/password fields), C103403
(Bearer token in header and JSON body).
This is never negotiable.

**IC-2:**
`tokenise_pii()` and `assert_no_raw_pii()` both execute to completion before
`write_record()` is called for any AppRecord. Enforcement has two paths:
(1) static PII field tokenisation per the `pii.fields` inventory in
`client_config.SOC_*.yaml`; (2) pattern-based ExtraColumns scan
(`_scan_extra_columns_for_pii()`) against all `extra_columns` values before
write — scanning values, not field names. A record for which
`assert_no_raw_pii()` raises or returns a PII-detected signal must never
reach DataLake=Y. The assertion is a write gate, not a logging step.
This is never negotiable.

**IC-3:**
Application identifiers (`app_id_canonical`, `app_id_raw`, `debtor_number`,
`sequence_id`) must be preserved without loss, truncation, overflow, or
collision at every pipeline stage — manifest classification, grouping,
deduplication, lineage construction, and DataLake write. In practice: stored
as strings at every stage; no cast to int, bigint, or any numeric type at any
point. Both `app_id_raw` (original, including `_test` suffix if present) and
`app_id_canonical` (normalised) must be present in lineage on every output
record.
This is never negotiable.

**IC-4:**
No credential value (OAuth token, bearer token, password, API key, or client
secret) may exist in any persisted record, log entry, lineage field, quarantine
record, or DataLake row — regardless of storage technology, pipeline stage, or
connector. This constraint applies to all future connector additions and
enhancement work, not only to the three connectors currently in scope.
This is never negotiable.

**IC-5:**
Raw applicant PII (SSN, SIN, full name, date of birth, address, phone number,
email address) may never exist in DataLake=Y output. This is a regulatory and
compliance constraint that holds independently of pipeline architecture, storage
technology, or connector configuration.
This is never negotiable.

---

## Section 3 — Scope Boundary

**CC may create or modify these files only:**

```
scripts/ingest_lib.py
assets/client_config.SOC_USA.yaml          (structural validation only — no <FILL:> population)
assets/client_config.SOC_CAN.yaml          (structural validation only — no <FILL:> population)
assets/field_mapping.SOC_USA.xlsx          (structural validation only — no field population)
assets/field_mapping.SOC_CAN.xlsx          (structural validation only — no field population)
tests/unit/test_*.py                       (new test files per task)
tests/integration/test_*.py               (new integration test files per task)
tests/fixtures/README.md
tests/fixtures/.gitignore
.gitignore
PROJECT_MANIFEST.md                        (registration updates only)
```

**CC must not:**
- Pre-populate any `<FILL:...>` placeholder in either config file
- Populate any field mapping row in either `.xlsx` file
- Modify `docs/ARCHITECTURE.md`, `docs/INVARIANTS.md`, `docs/EXECUTION_PLAN.md`,
  or `docs/PHASE4_GATE_RECORD.md`
- Create files outside the directories listed above
- Implement the `fff` parse strategy body — stub only, with `TODO(Q-FFF)` comment
- Read any file not registered in `PROJECT_MANIFEST.md` as authoritative input
- Use `eval()` — use `ast.literal_eval()` exclusively for Python repr parsing
- Add any code path that calls `write_record()` before `tokenise_pii()` has returned
- Add any code path that calls `write_record()` before `validate()` has returned

**If a task prompt conflicts with an invariant: the invariant wins.
Flag the conflict explicitly — never resolve it silently.**

---

## Section 4 — Fixed Stack

**Language:** Python 3.11+

**Engine file:** `scripts/ingest_lib.py` (project skill — extend; do not fork)

**Dependencies (install via pip):**
```
pyyaml>=6.0
openpyxl>=3.1
xmltodict>=0.13
pytest>=8.0
```

**No additional dependencies** may be introduced without engineer approval.
If a task appears to require a new library, flag it before installing.

**Testing framework:** pytest — all tests in `tests/unit/` or `tests/integration/`

**Config files:**
- `assets/client_config.SOC_USA.yaml` — USA pipeline config
- `assets/client_config.SOC_CAN.yaml` — CAN pipeline config
- `assets/field_mapping.SOC_USA.xlsx` — USA field mapping sheet
- `assets/field_mapping.SOC_CAN.xlsx` — CAN field mapping sheet

**Reference (read-only):**
- `references/mapping_schema.md` — parse strategy and transform contract

**Sample fixture:** `tests/fixtures/soc_sample.zip` — engineer-placed; not committed to Git

**Environment variables:** None required for the stub implementation.
Real DataLake adapter (TODO — team) will declare its own when implemented.

**Parse strategies registered in engine (`@strategy` decorator):**
`gds_envelope_json`, `raw_json`, `xml_dict`, `soap_xml`, `fff` (stub),
`binary_external_ref`, `credential_discard`

**Transforms registered in engine (`apply_transform` dispatch):**
`date_to_utc_iso`, `string_to_numeric`, `split_on_delim`, `json_double_parse`,
`ast_literal_eval`, `base64_extract`

**FFF parser:** stub only — raises `NotImplementedError` with `TODO(Q-FFF)` comment.
Do not implement the FFF parser body. Implementation is gated on Q-FFF resolution.

---

## Section 5 — Rules

**Rule 1:** All file references use full paths from repo root — never bare filenames.

**Rule 2:** All files inside any enhancement package carry their ENH-NNN prefix —
no exceptions.

**Rule 3:** Any file not in the mandatory set for its directory and not registered
in `PROJECT_MANIFEST.md` must not be read by CC as authoritative input. CC flags
unregistered files and reports them to the engineer before proceeding.
