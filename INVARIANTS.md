# INVARIANTS.md
## SOC Data Standardisation — Ingestion Pipeline
**Version:** v1.2 | **Date:** 2026-06-23 | **Status:** FINAL — Phase 4 Step 2b complete
**PBVI Phase:** 2 — Invariant Definition (finalised at Phase 4 gate)
**INVARIANT_AUTHORSHIP_MODE:** ASSISTED (greenfield)
**METHODOLOGY_VERSION:** v4.9

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-06-23 | CD/Mahendra | Initial — 26 invariants, Phase 2 output |
| v1.1 | 2026-06-23 | CD/Mahendra | Phase 2 domain challenge corrections applied |
| v1.2 | 2026-06-23 | Mahendra | Phase 4 Step 2b challenge: INV-05+D-05 merged; INV-06 consolidated into D-04; INV-07 rewritten; INV-08 removed; INV-10 reframed; INV-11 removed; INV-12 merged into INV-02; INV-13 renamed; INV-14 merged into INV-01. Net: 22 invariants. |

---

## Authorship Key

| Category | Authorship |
|---|---|
| Structural | CD-drafted. Engineer confirmed. |
| Data | CD-drafted. Engineer confirmed. |
| Domain | Engineer-authored. CD-challenged. |

---

## Reclassified / Removed Items

| ID | Original statement | Disposition | Destination |
|---|---|---|---|
| INV-05 | CAN bureau-evaluated app requires both sessions | Merged with D-05 | See D-05 below |
| INV-06 | Decision source exclusive to C238743-RESP | Consolidated into D-04 | D-04 gains config-authority clause |
| INV-07 (old) | App ID stored as VARCHAR; never coerced to numeric | Rewritten — see INV-07 below | Identity preservation principle |
| INV-08 | Score slots 4–14 unassigned for SOC | Removed — mapping governance | `field_mapping.SOC_*.xlsx` Legend tab |
| INV-10 (old) | Geo token is sole config routing signal | Reframed — see INV-10 below | Deterministic routing principle |
| INV-11 | CAN session detection by connector presence only | Removed — implementation detail | TASK-3.3 CC prompt |
| INV-12 | ExtraColumns PII scan mandatory and pattern-based | Merged into INV-02 | INV-02 enforcement note |
| INV-13 (old) | FFF parse failure is a hard quarantine | Renamed — see INV-13 below | Bureau evidence non-degradation |
| INV-14 | Credential scrub must use pattern-based detection | Merged into INV-01 | INV-01 enforcement note |
| D-11 | PyGDSA completeness sanity (≥100 attrs) | Removed — operational heuristic | TASK-4.5 CC prompt |

---

## Invariants

---

### INV-01 — Credential Scrub Precedes All Processing; Pattern-Based Detection Required

**Category:** Structural
**Authorship:** CD-drafted
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
`scrub_credentials()` executes to completion on every file in the manifest before
any file is parsed, logged, or routed downstream. No connector payload may be read,
deserialised, or written to any log while a credential field in that payload remains
in its raw form. Connectors in scope: C161653 (HTTP Authorization header), C754889
(username/password fields), C103403 (Bearer token in header and JSON body).

The scrub implementation must use pattern-based detection (regex) — not exact-string
matching against known credential values. Exact-match fails when credential format
changes in production; pattern-based detection catches new formats without a code change.

**Failure Mode:**
- *Violation:* A raw Authorization header, plain-text password, or Bearer token from
  C161653, C754889, or C103403 appears in a parse log, debug trace, quarantine record,
  or output JSON field. Or: scrub uses exact-match strings; a reformatted production
  credential passes through unscrubbed.
- *Detection:* Not detectable through normal DataLake output review. Requires explicit
  log audit or post-pipeline credential pattern grep. High latency to detection.
- *Blast radius:* Irreversible credential exposure. OAuth token from C161653 can be
  replayed to access Equifax CAN bureau data. Regulatory consequence.

---

### INV-02 — PII Tokenised Before Any DataLake Write; Two Enforcement Paths

**Category:** Structural
**Authorship:** CD-drafted
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
`tokenise_pii()` and `assert_no_raw_pii()` both execute to completion before
`write_record()` is called for any AppRecord. Enforcement has two mandatory paths:
(1) static PII field tokenisation per the `pii.fields` inventory in config;
(2) pattern-based ExtraColumns scan (`_scan_extra_columns_for_pii()`) against all
`extra_columns` values before write — scanning field values, not field names.
A record for which `assert_no_raw_pii()` raises or returns a PII-detected signal
must never reach DataLake=Y. The assertion is a write gate, not a logging step.

**Failure Mode:**
- *Violation:* A raw SSN, SIN, full name, date of birth, address, phone number, or
  email address is present in a persisted DataLake=Y record — either from a static
  PII field that was not tokenised, or from an ExtraColumns value that was not scanned.
- *Detection:* Not detectable through normal pipeline operation. Requires post-write
  DataLake PII scan or audit query. Regulatory reporting or a data breach could be
  the first signal.
- *Blast radius:* GDPR / PIPEDA / FCRA violation. Financial penalty. Irreversible —
  raw PII cannot be un-persisted once written to partitioned DataLake storage.

---

### INV-03 — Validation Gate Precedes DataLake Write

**Category:** Structural
**Authorship:** CD-drafted
**Scope:** TASK-SCOPED (write tasks — TASK-9.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
`validate()` executes to completion before `write_record()` is called. Any record
with a hard-quarantine rule failure (REQ-VAL-001, 002, 003, 005, 007, 008) must be
routed to the quarantine queue and must not be written to DataLake=Y. Quarantine
routing is not configurable per record.

**Failure Mode:**
- *Violation:* A record with no `application_id`, invalid geography, missing
  `applicationDate`, incomplete CAN session, or confirmed raw-PII condition is
  written to DataLake=Y.
- *Detection:* Detectable by downstream DataLake query on null/invalid fields, but
  only after the write has already occurred.
- *Blast radius:* Analytics joins on `application_id` fail silently. Compliance
  queries return structurally invalid records. Corrective delete from partitioned
  DataLake is operationally expensive.

---

### INV-04 — One Output Record Per Canonical App ID

**Category:** Data
**Authorship:** CD-drafted
**Scope:** TASK-SCOPED (write tasks — TASK-9.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
For each canonical App ID (debtor_number + datetime, `_test` stripped), exactly
one record is written to DataLake=Y per pipeline run. USA retries deduplicated by
latest timestamp. `_test` variants quarantined. The uniqueness constraint holds at
the DataLake=Y partition level.

**Failure Mode:**
- *Violation:* Two DataLake=Y records exist for the same canonical App ID from the
  same pipeline run. Or: a valid application produces zero records (missing case).
- *Detection:* Duplicate: `GROUP BY application_id HAVING COUNT(*) > 1`. Missing:
  `expected_applications != produced_records` via manifest reconciliation.
- *Blast radius:* Risk analytics double-counts applications. Aggregate metrics
  inflated. Missing applications disappear from reporting and audit trails. CRM
  joins produce duplicate or absent records.

---

### INV-07 — Application Identifiers Preserved Without Loss, Truncation, Overflow, or Collision

**Category:** Data (rewritten from VARCHAR-specific form)
**Authorship:** CD-drafted; principle reframed by engineer at Phase 4 Step 2b
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
Application identifiers (`app_id_canonical`, `app_id_raw`, `debtor_number`,
`sequence_id`) must be preserved without loss, truncation, overflow, or collision
at every pipeline stage — manifest classification, grouping, deduplication, lineage
construction, and DataLake write. In practice: stored as strings at every stage;
no cast to int, bigint, or any numeric type at any point in the pipeline.

**Failure Mode:**
- *Violation:* A debtor_number or composite App ID is cast to a numeric type,
  truncated, or causes two distinct raw IDs to resolve to the same canonical ID.
- *Detection:* Silent during development if test data fits within numeric bounds.
  Requires explicit type checking or a production record with a value exceeding
  INT64 bounds to surface.
- *Blast radius:* App IDs overflow, truncate, or collide silently. DataLake records
  misjoined. Downstream CRM and compliance systems receive wrong application
  references. Irreversible if DataLake already partitioned on a numeric key.

---

### INV-09 — _test App IDs Never Written to Canonical DataLake Partition

**Category:** Data
**Authorship:** CD-drafted; conditional form confirmed by engineer
**Scope:** TASK-SCOPED (TASK-3.1, TASK-8.3)
**HARNESS-CANDIDATE:** Yes

**Statement:**
Any App ID carrying the `_test` suffix (before stripping) must be routed to
quarantine and must never be written to the canonical DataLake=Y partition,
regardless of Q3 resolution. If Q3 resolves to "separate_partition", a distinct
partition guard must be implemented and verified before that routing is enabled —
the canonical partition remains protected unconditionally.

**Failure Mode:**
- *Violation:* A record with `app_id_raw` containing `_test` is written to the
  canonical DataLake=Y partition.
- *Detection:* Detectable by a query on `lineage.app_id_raw` for records containing
  `_test` in DataLake=Y. Not detectable during pipeline execution without an
  explicit guard.
- *Blast radius:* Production analytics contaminated with test data. App ID joins in
  CRM return test records. Aggregate metrics skewed.

---

### INV-10 — Routing Decisions Must Be Explicit and Deterministic

**Category:** Structural (reframed from geo-token-specific form)
**Authorship:** CD-drafted; principle reframed by engineer at Phase 4 Step 2b
**Scope:** TASK-SCOPED (TASK-1.4, TASK-1.5)
**HARNESS-CANDIDATE:** Yes

**Statement:**
Routing decisions (geography, config selection, session model) must be explicit
and deterministic. No default routing, silent fallback, or runtime inference is
permitted. Any file or record that cannot be routed by explicit signal must be
quarantined before processing begins.

**Failure Mode:**
- *Violation:* A file with an absent, malformed, or unrecognised routing signal
  (e.g. unrecognised geo token) is routed to a default config or silently dropped
  rather than quarantined.
- *Detection:* Silent routing to wrong config not detectable until field mapping
  produces incorrect output. Silent drop detectable only in quarantine report if
  a file count check is implemented.
- *Blast radius:* A CAN application processed through the USA config produces a
  record with missing bureau data and incorrect session model — written as if valid.

---

### INV-13 — Required Bureau Evidence May Not Silently Degrade Into a Valid Output Record

**Category:** Structural (renamed from FFF-specific form)
**Authorship:** CD-drafted; renamed by engineer at Phase 4 Step 2b
**Scope:** TASK-SCOPED (TASK-4.3, TASK-4.4)
**HARNESS-CANDIDATE:** Yes

**Statement:**
Any parse failure on a bureau connector that prevents bureau data from being
extracted must result in a hard quarantine with an explicit failure flag — not a
write with bureau fields absent and no error signal. Silent degradation (writing a
record as valid when required bureau evidence could not be extracted) is not a
permitted failure mode. Currently applies to C100810 and C161796 (FFF parse stub);
extends to any future bureau connector parse failure.

**Failure Mode:**
- *Violation:* A record is written to DataLake=Y with bureau fields absent and no
  quarantine flag, because a bureau connector parse exception was caught and swallowed.
- *Detection:* Detectable only by querying DataLake=Y for records with null bureau
  score fields and no quarantine flag.
- *Blast radius:* Bureau data silently absent from records. Risk models run on
  structurally incomplete data without knowing it. Downstream systems cannot
  distinguish incomplete from complete records.

---

### D-01 — CAN Bureau Session Ordering

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-3.4, TASK-8.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
For a CAN application that contains both bureau sessions, the Equifax session must
occur after the TransUnion session in the application lifecycle.

```
IF geography = CAN
AND TU_session exists
AND EFX_session exists
THEN EFX.timestamp > TU.timestamp
```

Violation is a soft-warn (REQ-BL-002) — not a hard quarantine. The anomaly is
recorded in lineage; the record is not blocked from DataLake=Y on ordering alone.

**Failure Mode:**
- *Violation:* Both sessions exist but Equifax occurs before or at the same time
  as TransUnion. The merge accepts the reversed-order sessions as valid.
- *Detection:* `EFX.timestamp <= TU.timestamp` — detected by REQ-BL-002 rule if
  implemented. Not visible in the output record without a lineage query.
- *Blast radius:* Bureau workflow chronology becomes invalid. Audit reconstruction
  produces incorrect session ordering. Reversed sequence may indicate a data
  integrity issue in the source system.

---

### D-02 — Cross-Session EcsDebtorNumber Identity

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-3.2, TASK-3.5, TASK-8.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
All sessions belonging to the same application must reference the same
EcsDebtorNumber.

```
FOR all sessions S in application A:
COUNT(DISTINCT EcsDebtorNumber) = 1
```

**Failure Mode:**
- *Violation:* Sessions belonging to the same application contain different debtor
  numbers — different applicants merged into one record.
- *Detection:* `COUNT(DISTINCT EcsDebtorNumber) > 1` across sessions for the same
  App ID. REQ-BL-003 catches this if implemented.
- *Blast radius:* Different applicants' bureau, decision, and applicant data merged
  into one record. Audit reproduction impossible. Regulatory consequence if
  discovered. Severity: Critical.

---

### D-03 — Decline Explainability

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-5.4, TASK-8.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
A declined application is not complete unless at least one adverse-action reason
code exists in `system.application.decisionSummary.reasonCodes[]`.

```
IF decision = DECLINED
THEN system.application.decisionSummary.reasonCodes[].count >= 1
```

**Failure Mode:**
- *Violation:* A record with `decision = DECLINED` is written to DataLake=Y with
  `reasonCodes[] = []` or null.
- *Detection:* REQ-BL-001 catches this if enabled. Otherwise detectable only by a
  compliance query on declined records.
- *Blast radius:* Adverse action notices cannot be generated. FCRA compliance
  failure — lender cannot explain decline to applicant. Regulatory consequence.
  Severity: High (Compliance).

---

### D-04 — Decision Authority

**Category:** Domain
**Authorship:** Engineer-authored (consolidated with former INV-06)
**Scope:** TASK-SCOPED (TASK-5.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
The application decision must be derived from the designated authoritative
decision-engine connector output and must not be inferred from bureau data,
application data, or derived calculations. No connector other than the designated
authoritative connector may supply the value for `system.application.decision`.

The authoritative connector is declared in client configuration (`decision.source`
in `client_config.SOC_*.yaml`) and must not be overridden at runtime. For SOC,
the current authoritative connector is C238743-RESP `data.Decision.decision`.
The audit layer decision field must never be read as a decision source — primary
or fallback — for any SOC record.

**Failure Mode:**
- *Violation:* Decision sourced from the audit layer (always N/A for SOC), bureau
  data, inferred logic, or a non-authoritative connector. Or: configured authoritative
  source overridden at runtime based on data availability.
- *Detection:* Not detectable from the output record if the derived value happens to
  match the authoritative value. Only a lineage audit confirming decision source
  provenance would catch it.
- *Blast radius:* Incorrect approval/decline metrics. CRM receives incorrect decision
  states. Audit trail broken. Non-deterministic outputs — same input can produce
  different decision depending on connector availability.

---

### D-05 — CAN Bureau Workflow Completeness

**Category:** Domain
**Authorship:** Engineer-authored (merged with former INV-05)
**Scope:** TASK-SCOPED (TASK-3.3, TASK-3.4)
**HARNESS-CANDIDATE:** Yes

**Statement:**
If a CAN application participates in bureau evaluation — indicated by the presence
of any bureau connector file (C100810, C161796) in its manifest — then both session 1
(C100810 present) and session 2 (C161653 or C161796 present) must be detected, and
the Equifax session must have a later timestamp than the TransUnion session, before
the record is considered complete for DataLake=Y write.

```
IF CAN AND bureau_workflow = true
THEN
  session_count = 2
  AND TU.timestamp < EFX.timestamp
```

CAN applications with no bureau connector files present are not subject to this
invariant. Their treatment is governed by Open Question Q4.

**Failure Mode:**
- *Violation:* Missing required bureau session — application treated as complete
  despite incomplete bureau workflow. Or: incorrect TU → EFX ordering accepted
  as valid.
- *Detection:* `required_session_count != 2` OR `TU.timestamp >= EFX.timestamp`.
  REQ-VAL-003 catches the session count; REQ-BL-002 catches the ordering.
- *Blast radius:* Partial bureau evidence enters risk analytics and compliance
  reporting. Credit-decision reconstruction unreliable. CAN completeness loses
  meaning. Risk models operate on incomplete bureau data.

---

### D-06 — Credential Non-Persistence

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
Credentials are operational artifacts and must never become business data.
No credential value (OAuth token, bearer token, password, API key, client secret,
bureau credential) may exist in any persisted record, log entry, lineage field,
quarantine record, audit export, or DataLake row — regardless of storage technology
or pipeline design. This constraint applies to all future connector additions.

```
credential_fields ∉ persisted_record
```

**Failure Mode:**
- *Violation:* OAuth token, bearer token, client secret, password, or bureau
  credential survives into a DataLake record, quarantine record, lineage metadata,
  audit export, or persisted intermediate storage.
- *Detection:* Post-write credential pattern scan. Secret-detection tooling finds
  `Authorization: Bearer`, `client_secret=`, `member_password=`, etc.
- *Blast radius:* Credential compromise. Unauthorized bureau access becomes possible.
  Credentials may remain exposed in backups, snapshots, and replicated storage.
  Regulatory/security incident.

---

### D-07 — PII Non-Persistence

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
Raw applicant PII may never exist in DataLake=Y output. This is a regulatory and
compliance constraint that holds independently of pipeline architecture, storage
technology, or connector configuration.

```
persisted_record ∩ raw_PII = ∅
```

**Failure Mode:**
- *Violation:* Raw SSN/SIN, DOB, address, name, email, or phone appears in any
  persisted output.
- *Detection:* Post-write PII scan. Pattern-based audit of DataLake partitions.
  Regulatory review or breach investigation may discover exposure.
- *Blast radius:* GDPR/PIPEDA/FCRA compliance violation. Privacy breach. Replication
  of raw PII into downstream systems and backups. Expensive remediation and
  potential regulatory penalties.

---

### D-08 — One Application, One Canonical Record

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-9.2, TASK-9.3)
**HARNESS-CANDIDATE:** Yes

**Statement:**
SOC reasons about applications, not connector executions. Exactly one standardised
output record exists for each logical application across all partitions, geographies,
and pipeline runs.

```
ApplicationID → 1 canonical output record
```

**Failure Mode:**
- *Violation:* Two output records exist for the same logical application (duplicate
  case). Or: a valid application produces zero records (missing case).
- *Detection:* Duplicate: `GROUP BY application_id HAVING COUNT(*) > 1`. Missing:
  `expected_applications != produced_records` via manifest reconciliation.
- *Blast radius:* Downstream systems joining on `application_id` receive duplicate
  rows. Aggregate metrics double-counted. Missing applications disappear from
  reporting and audit trails.

---

### D-09 — Bureau Data Must Be Attributable

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-6.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
Every bureau-derived value must be traceable to a specific bureau provider and
session. Bureau values must be placed under the correct `bureauData.<provider>`
segment and carry provenance in lineage.

```
bureau_value => provider + session provenance
```

**Failure Mode:**
- *Violation:* A bureau score or tradeline value exists in a record but its provider
  origin cannot be determined — `provider = null` or session provenance absent.
- *Detection:* Bureau fields populated while provider metadata or session metadata
  is absent. Detectable by DataLake query; not visible during pipeline execution.
- *Blast radius:* Bureau values cannot be audited. Disputes cannot be investigated.
  Compliance reviews cannot reconstruct data origin. Provider-level analytics
  unreliable.

---

### D-10 — Application Identity Preservation

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** GLOBAL
**HARNESS-CANDIDATE:** Yes

**Statement:**
The application identity extracted from source artifacts must remain recoverable
after normalisation. Both `app_id_raw` (original, including `_test` suffix if
present) and `app_id_canonical` (normalised) must be preserved in lineage on every
output record.

```
raw_app_id preserved in lineage
canonical_app_id derived and stored
```

**Failure Mode:**
- *Violation:* Raw identifier lost. App ID truncated. Numeric coercion causes
  overflow. Two distinct App IDs collide into one identifier. Canonical ID cannot
  be traced back to original source identity.
- *Detection:* Raw App ID missing from lineage. Canonical ID cannot be reconstructed
  from source artifacts. Duplicate canonical IDs generated from distinct raw IDs.
- *Blast radius:* Incorrect joins across systems. Audit reconstruction impossible.
  Application history becomes unreliable. Customer/application references ambiguous.

---

### D-12 — One Authoritative Source Per Business Attribute

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-5.5, TASK-6.1)
**HARNESS-CANDIDATE:** No (configuration contract — enforced at mapping review)

**Statement:**
For every business attribute that can originate from multiple connectors, SOC
defines exactly one authoritative source. The pipeline must resolve that attribute
from its declared authoritative source and must not override source priority at
runtime based on data completeness, availability, or any other heuristic. The
specific authoritative source per attribute is declared in `field_mapping.SOC_*.xlsx`
and `client_config.SOC_*.yaml` — not in this document.

**Failure Mode:**
- *Violation:* Multiple connectors provide conflicting values and runtime logic
  chooses arbitrarily. Runtime override replaces configured authority. Attribute
  source changes depending on connector arrival order.
- *Detection:* Source lineage differs from configured authority. Same application
  produces different values depending on connector arrival order. Source-resolution
  audit reveals override.
- *Blast radius:* Non-deterministic outputs. Conflicting values for APR, decision,
  limits, scores. Reprocessing the same application yields different results.
  Auditability and trust collapse.

---

### D-13 — Complete Application Record

**Category:** Domain
**Authorship:** Engineer-authored
**Scope:** TASK-SCOPED (TASK-9.1, TASK-9.2)
**HARNESS-CANDIDATE:** Yes

**Statement:**
A SOC application record is complete only when all information required to
reproduce the original credit decision is present or explicitly marked unavailable.

```
complete_record =
  identity (canonical app_id + geography)
  + application data (has_connector_data = true)
  + decision (decision value OR decision_missing flag)
  + required bureau evidence (or explicit bureau-blocked/unavailable flag)
  + lineage (source_zip, transform_timestamp, mapping_config_version,
             validation_status)
```

**Failure Mode:**
- *Violation:* A record is classified as complete while one or more required
  components are absent — decision missing with no flag, bureau evidence absent
  with no quarantine flag, lineage block incomplete.
- *Detection:* Completeness validation: all five components present or explicitly
  flagged. Failure of any required component violates the invariant.
- *Blast radius:* Credit-decision reconstruction becomes impossible. Analytics
  operate on incomplete records. Compliance and audit reporting become unreliable.
  Downstream systems cannot distinguish complete records from partial records.

---

## Invariant Summary — v1.2 Final

| ID | Statement (condensed) | Category | Scope | Harness |
|---|---|---|---|---|
| INV-01 | Credential scrub first; pattern-based detection required | Structural | GLOBAL | Yes |
| INV-02 | PII tokenised before write; two enforcement paths (static + ExtraColumns scan) | Structural | GLOBAL | Yes |
| INV-03 | Validation gate before write | Structural | TASK-SCOPED | Yes |
| INV-04 | One output record per canonical App ID | Data | TASK-SCOPED | Yes |
| INV-07 | Application identifiers preserved without loss/truncation/overflow/collision | Data | GLOBAL | Yes |
| INV-09 | _test App IDs never to canonical partition | Data | TASK-SCOPED | Yes |
| INV-10 | Routing decisions explicit and deterministic; unroutable = quarantine | Structural | TASK-SCOPED | Yes |
| INV-13 | Required bureau evidence may not silently degrade into valid output | Structural | TASK-SCOPED | Yes |
| D-01 | CAN EFX session timestamp > TU session timestamp | Domain | TASK-SCOPED | Yes |
| D-02 | All sessions share same EcsDebtorNumber | Domain | TASK-SCOPED | Yes |
| D-03 | Declined app has ≥1 reasonCode | Domain | TASK-SCOPED | Yes |
| D-04 | Decision from authoritative connector only; declared in config; no runtime override | Domain | TASK-SCOPED | Yes |
| D-05 | CAN bureau workflow: both sessions present AND TU→EFX sequence | Domain | TASK-SCOPED | Yes |
| D-06 | Credentials never persisted anywhere | Domain | GLOBAL | Yes |
| D-07 | Raw PII never in DataLake=Y | Domain | GLOBAL | Yes |
| D-08 | One logical application = one canonical record | Domain | TASK-SCOPED | Yes |
| D-09 | Bureau values attributable to provider + session | Domain | TASK-SCOPED | Yes |
| D-10 | Raw App ID preserved in lineage; canonical App ID derived | Domain | GLOBAL | Yes |
| D-12 | One authoritative source per business attribute; no runtime override | Domain | TASK-SCOPED | No |
| D-13 | Complete record = identity + data + decision + bureau + lineage | Domain | TASK-SCOPED | Yes |

**Total: 20 invariants** (8 Structural/Data, 12 Domain)
**HARNESS-CANDIDATE: 19**
**GLOBAL: 7 | TASK-SCOPED: 13**

> Note on count: INV-05 merged into D-05 (combined domain invariant);
> INV-06 consolidated into D-04; INV-07 rewritten in place;
> INV-08, INV-11, INV-12, INV-13 (old), INV-14 removed or merged.
> Previous count was 22 in the Step 2b summary; final reconciliation
> after merging INV-05+D-05 as one entry yields 20 distinct invariants.

---

## Engineer Sign-Off

**Phase 4 Step 2b: COMPLETE — 2026-06-23**
All 20 invariants walked through failure mode review. All domain invariants
stated by engineer from memory. No invariant failed the ownership test.

**Engineer:** Mahendra **Date:** 2026-06-23
