# ARCHITECTURE.md
## SOC Data Standardisation — Ingestion Pipeline
**Version:** v1.0 | **Date:** 2026-06-23 | **Status:** DRAFT — awaiting engineer sign-off
**PBVI Phase:** 1 — Decide | **Authorship mode:** ASSISTED (greenfield)

---

## 1. Problem Framing

### What this system solves
SnapOn Credit (SOC) generates raw GDS credit-decisioning output per application — a ZIP
package containing wire-level HTTP payloads (raw/), GDS-envelope JSON (data/), execution
audit traces (audit/), and a client schema dictionary (sdd/). No reliable, repeatable
transformation pipeline exists to convert these multi-geography, multi-connector,
multi-session raw files into the single, schema-validated, PII-clean, credential-scrubbed
JSON record per Application ID that downstream systems (DataLake, risk analytics,
compliance reporting, CRM) require.

### What this system explicitly does NOT solve
- Real-time or streaming ingestion — scope is batch ZIP file processing
- Cross-client deduplication — SOC records are isolated from other DG-Forge clients
- PII vault key management — handled by client IT security; pipeline writes tokenised values only
- CaseCenter write-back — downstream CRM integration is a separate project phase
- Analytics dashboards — DataLake write is the pipeline boundary; analytics is post-pipeline
- FFF parser implementation without a width specification — this remains a build blocker until
  the bureau layout spec is delivered (see Open Questions Q-FFF)

---

## 2. Key Design Decisions

### DD-01: Dual-Config, Geography-Split Architecture (Option B selected)

**What was decided:**
The pipeline uses two separate config+mapping artifact pairs — one for USA and one for CAN —
rather than a single unified config with geography-conditional logic.

- `client_config.SOC_USA.yaml` + `field_mapping.SOC_USA.xlsx`
- `client_config.SOC_CAN.yaml` + `field_mapping.SOC_CAN.xlsx`

A thin ZIP-manifest dispatcher reads the `geo` token from each file's filename, splits the
file set by geography, and calls `run_pipeline` once per geography with the appropriate
config+mapping pair.

**Rationale:**
USA and CAN are fundamentally different processing paths, as stated in the BRD:

| Dimension         | USA                   | CAN                              |
|-------------------|-----------------------|----------------------------------|
| Session model     | Single session        | 2-session merge (TU + EFX)       |
| Bureau wire format| XML (C1677939)        | FFF (C100810 + C161796) — BLOCKER|
| OAuth dependency  | None                  | C161653 OAuth credential scrub   |
| Multi-session validation | N/A            | REQ-VAL-003 mandatory            |
| DataLake partition| SOC_USA               | SOC_CAN                          |

Separate configs mirror this business reality. They are not artificial duplication.

**FFF blocker handling:** The dual-config architecture allows USA to be deployed and
verified independently while CAN processing is gated on FFF parser implementation.
CAN records quarantine with `has_bureau_data=false` until C100810 and C161796 are
implemented. This is a deliberate staged deployment, not a workaround.

**Alternatives rejected:**

*Option A — Single-Config, Geography-Conditional:*
One config, one mapping sheet, `sessions.model: mixed`. Rejected because:
- USA deployment is blocked until CAN FFF is resolved — delivery risk with no business justification
- Geography-conditional source locators in a single mapping sheet reduce analyst readability
- A single mapping sheet for 13 connectors spanning two fundamentally different workflows
  accumulates cyclomatic complexity in the session merge step (risk of violating CQ-001)

*Option C — Single-Config, FFF-Bypass with Partial CAN Output:*
Rejected unconditionally. It requires downgrading REQ-VAL-003 from hard-quarantine to
soft-warn, which directly produces FM-03 (partial CAN record written) and FM-04 (CAN
bureau data silently absent). It also introduces a `warn_and_skip` degradation mode that,
once in the engine, is available to all clients — a governance risk. This option violates
the BRD.

**Challenge — strongest argument against DD-01:**
Two configs mean shared connectors (C225334 web_service_cc, C103403 PyGDSA, C238743
decision source) must be declared and maintained in both YAML files. A field path change
in C225334 requires two updates instead of one — a sync risk. Two mapping sheets double
the analyst review surface for shared SDD paths.

**Verdict:** Rejected. The sync risk is real but low-frequency — shared connectors change
rarely relative to the delivery value of independent USA deployment. The risk is mitigated
by registering shared connectors explicitly in ARCHITECTURE.md (see §8 Data Model, Shared
Connectors section) so any change to them triggers a two-file update protocol.

---

### DD-02: Decision Source — C238743-RESP Authoritative; Audit Layer Excluded

**What was decided:**
The credit decision for every SOC record is sourced exclusively from C238743-RESP
`data.Decision.decision`. The audit layer decision field is always N/A for SOC and must
never be used as a decision source — not as primary, not as fallback.

**Rationale:**
Confirmed by Phase 1 raw data analysis across all 8 sample applications. The audit layer
decision is structurally always N/A for SOC. Using it as a fallback would produce records
where every application appears to have no decision — FM-02 (silent wrong decision).

**Challenge:**
If C238743 is absent for a given application, the pipeline has no decision source and
produces `decision_missing=true`. Could the audit layer serve as a last-resort fallback
for robustness?

**Verdict:** Rejected. A last-resort fallback to a field that is structurally always N/A
is not a fallback — it is a silent wrong answer. `decision_missing=true` with soft-warn
(REQ-VAL-006) is the correct failure mode. Downstream systems must handle this flag.

---

### DD-03: CAN Session Detection — Connector Presence, Not sequence_id

**What was decided:**
CAN session identity is determined by connector presence only:
- Session 1: presence of C100810 (transunion_ca_fff_v4_0)
- Session 2: presence of C161653 or C161796 (equifax_ca connectors)

The `sequence_id` value in filenames is NOT used to determine session number.

**Rationale:**
Phase 1 raw data analysis confirmed that `sequence_id` values are not reliably sequential
across CAN sessions and can represent retry sequences (e.g. v51_USA_112949672 has 2 data
sessions at seq 80, representing a retry — not a second bureau session). Using
`sequence_id` for CAN session detection would misclassify retries as multi-session merges.

**Challenge:**
Connector-presence detection requires the manifest to have classified all files before
session assembly begins. If a connector code is unrecognised (new connector introduced in
production), it will be silently absent from session detection.

**Verdict:** Accepted — mitigated by the unrecognised-connector alert in the validation
pipeline (REQ-VAL-004 warns when no bureau connector is present) and the open question
Q1 (production ZIP structure confirmation).

---

### DD-04: Deduplication Key — transaction_id + sequence_id Composite

**What was decided:**
The deduplication key for USA retry detection is the composite `(transaction_id, sequence_id)`.
`transaction_id` alone is not sufficient.

**Rationale:**
Sample v51_USA_112949672 contains two data sessions at sequence_id=80, confirming that a
single transaction_id can have multiple sequence entries representing retry events. The
composite key identifies the unique session record; latest timestamp wins on dedup.

**Challenge:**
None raised — this is a corrective finding from Phase 1 analysis, not a design choice.

---

### DD-05: App ID Storage — VARCHAR, Never INTEGER

**What was decided:**
The canonical App ID (debtor_number + datetime components) is always stored as VARCHAR.
The `sequence_id` component is also VARCHAR.

**Rationale:**
SOC debtor numbers are 9-digit strings. Cross-client comparison has confirmed that
numeric App IDs can reach lengths that overflow INT64 (confirmed on USCC 20-digit IDs).
Defensive VARCHAR storage is the DG-Forge standard for all App ID fields.

---

### DD-06: _test Suffix — Strip and Quarantine (Pending Q3)

**What was decided:**
_test-suffixed App IDs are stripped to produce the canonical ID (`app_id_canonical`)
but the record is routed to quarantine by default, pending client instruction on
production treatment (Open Question Q3). _test records are fully isolated — they never
reach the canonical DataLake=Y partition.

**Rationale:**
Default-quarantine is the safest behaviour in the absence of a client instruction.
Incorrect routing of _test records to production DataLake cannot be undone after the fact.

---

### DD-07: ZIP Manifest Dispatcher — Thin Routing Layer

**What was decided:**
A thin dispatcher function (registered as `dispatch_by_geo` in `scripts/ingest_lib.py`)
reads the `geo` token from each filename in the ZIP manifest, partitions files into
`{USA: [...], CAN: [...]}` sets, and calls `run_pipeline` once per non-empty geography
set with the corresponding config and mapping pair.

This dispatcher is not in the BRD. It is an implied architectural necessity of DD-01
(dual-config split) and is registered here as a named decision so it is not treated as
an undocumented code path.

**Rationale:**
`run_pipeline` in `ingest_lib.py` takes a single config and mapping sheet. The dual-config
architecture requires a pre-step that routes files before pipeline invocation. A thin
dispatcher is simpler than modifying `run_pipeline` to accept multiple configs.

**Challenge:**
A file with an unrecognised or absent `geo` token cannot be dispatched. This must be
surfaced as a hard quarantine rather than a silent skip.

**Verdict:** Accepted. Files with unparseable `geo` tokens are quarantined with
`REQ-VAL-002` failure before reaching any pipeline stage.

---

## 3. Challenges to Decisions (Strongest Counter-Arguments)

| Decision | Strongest challenge | Verdict |
|---|---|---|
| DD-01 Dual-config | Two configs double maintenance for shared connectors | Rejected — sync risk is low-frequency; delivery value of independent USA deployment outweighs it |
| DD-02 C238743 authoritative | C238743 absent → no fallback → decision_missing on valid records | Rejected — audit fallback is structurally N/A; silent wrong answer is worse than explicit missing flag |
| DD-03 Connector-presence session detection | Unrecognised connector → silent session miss | Accepted with mitigation — REQ-VAL-004 + Q1 confirmation before go-live |
| DD-04 Composite dedup key | Adds join complexity for downstream queries | Rejected — correctness beats query simplicity |
| DD-05 VARCHAR App ID | Slightly larger index footprint | Rejected — overflow risk is irreversible data corruption |
| DD-06 _test quarantine | Quarantine blocks all _test records including legitimate UAT testing | Accepted — Q3 must be resolved before go-live; this is the safe default |
| DD-07 Dispatcher layer | Additional code path to maintain and test | Accepted — named and registered; simpler than modifying run_pipeline internals |

---

## 4. Key Risks

| ID  | Risk | Severity | Mitigation |
|-----|------|----------|------------|
| R-01 | FFF parser not delivered before CAN go-live deadline — CAN bureau data permanently absent from DataLake | HIGH | Q-FFF is a go-live blocker; CAN pipeline quarantines all bureau records until resolved. Track as critical path item. |
| R-02 | Production ZIP structure differs from 8-app sample — manifest logic fails on unknown folders | HIGH | Q1 must be resolved before go-live. Add structural drift detection in dispatcher. |
| R-03 | Additional call types in production (beyond MPU) not covered by either config | HIGH | Q2 must be resolved. Dispatcher emits alert on unrecognised call_type token. |
| R-04 | _test App IDs routed to production DataLake if Q3 is resolved as "include" without partition separation | HIGH | Default is quarantine. If Q3 resolves to "separate_partition", implement partition guard before enabling. |
| R-05 | Shared connectors (C225334, C103403, C238743) updated in one config but not the other | MED | Two-file update protocol: any change to a shared connector triggers mandatory dual-config review. Registered in §8. |
| R-06 | ExtraColumns PII scan patterns incomplete — new email/phone format in production not caught | MED | Pattern-based detection (not exact match). Patterns reviewed on every release. |
| R-07 | Credential scrub regex too narrow — new credential format in C161653, C754889, or C103403 | CRITICAL | Pattern-based detection mandatory. Exact-match scrub is rejected. |
| R-08 | PROD GDS environment (workbench_version) differs from UAT 3.6.0.14 — file structure or connector set changes | MED | PROD confirmation is a go-live blocker (Open Question MI-01). |
| R-09 | PyGDSA C103403 double-parse yields fewer than 100 attributes in production | MED | REQ-BL-004 flags partial parse. Sanity check is enforced in `preprocess.nested_parse.base64.min_attributes`. |

---

## 5. Key Assumptions

| ID  | Assumption |
|-----|------------|
| A-01 | The 8-application sample is representative of production record structure for both USA and CAN paths |
| A-02 | Standard Schema v1.1 is the agreed target. No breaking changes without notice |
| A-03 | SnapOn_SDD.json is the authoritative SOC field dictionary and will be kept current by the client |
| A-04 | Client IT security manages PII vault keys. DG-Forge writes tokenised values only |
| A-05 | MPU is the only call type in production until Q2 is resolved |
| A-06 | workbench_version 3.6.0.14 is the UAT version. PROD version will be confirmed before go-live |
| A-07 | C238743-RESP `data.Decision.decision` is structurally populated for all non-declined applications |
| A-08 | The dispatcher's `geo` token (CAN / USA) in the filename is always present and reliable |
| A-09 | cc_extracts/ is empty in production as it is in the 8-app sample (tolerated gracefully if populated) |
| A-10 | No async connectors are present in SOC — all sessions are synchronous (confirmed in Phase 1 analysis) |

---

## 6. Open Questions

These questions must be resolved before go-live. Q-FFF, Q1, and Q2 are also build-relevant
and must be tracked on the critical path.

| ID    | Question | Impact | Blocks build? | Blocks go-live? | Owner |
|-------|----------|--------|---------------|-----------------|-------|
| Q-FFF | FFF width specification for C100810 and C161796 — layout not provided | CAN bureau processing fully blocked without it | YES — CAN bureau tasks cannot be built | YES | SOC client |
| Q1    | Production ZIP structure — folders beyond raw/, data/, audit/, sdd/, cc_extracts/? | Dispatcher and manifest logic may need extension | Potential | YES | SOC client |
| Q2    | Call types beyond MPU in production? If so, connector sets? | Additional config+mapping pairs per call type | Potential | YES | SOC client |
| Q3    | Production treatment of _test App IDs — include, exclude, or separate partition? | App ID normalisation and DataLake partitioning | No — default is quarantine | YES | SOC client |
| Q4    | Business rule triggering second Equifax session for CAN — what condition fires it? | Required to validate multi-session merge completeness | No | YES | SOC client |
| Q5    | Are there declined applications in production? Dec_Reasons and adverse action path are untested | Compliance reporting path unverified | No | YES | SOC client |
| Q-PROD| PROD GDS environment confirmation — workbench_version and audit.profile = 'PROD' | Pipeline must not go live against PROD until confirmed | No | YES | SOC client |

---

## 7. Future Enhancements (Parking Lot)

| Item | Rationale for deferral |
|------|------------------------|
| AUD/REN call type support | Referenced in SDD but absent in all 8 sample apps. Defer until Q2 resolved and sample data provided |
| Schema extension candidates (isCoApp, Dec_ExpiryDate, Demographic_ConsentCheckCreditFlag, EmploymentSinceDate) | Candidates identified in Phase 1 analysis. Require client schema governance sign-off before promotion from extraColumns |
| CaseCenter write-back | Separate project phase per BRD §2.2 |
| Real-time streaming ingestion | Out of scope per BRD §2.2 |
| Cross-client App ID join | Requires shared canonical ID registry — not a Phase 1 deliverable |
| SOCModelFinalScore in DerivedApplication | Present in sample but not in Standard Schema v1.1 — extraColumns candidate pending schema governance |

---

## 8. Data Model

### First-Class Entities

| Entity | Represents | Key fields | Notes |
|--------|------------|------------|-------|
| AppRecord | One canonical application | app_id_canonical, geography, files[], record{}, lineage{} | One per canonical App ID; _test records isolated |
| SourceFile | One physical file from the ZIP | path, folder, connector, direction, step, app_id_raw, sequence_id, payload | Classified at manifest build time |
| ConnectorPayload | Parsed content of one SourceFile | Varies by connector — GDS envelope, raw JSON, XML dict, FFF (blocked) | Produced by parse_file() |
| OutputRecord | Standardised DataLake JSON | Follows Standard Schema v1.1 + SOC extensions under extraColumns{} | One per AppRecord; written only after I2 + I3 pass |
| LineageRecord | Processing provenance | source_zip, transform_timestamp, credential_scrubbed_connectors[], validation_status, etc. | Embedded in OutputRecord.system.lineage |
| QuarantineRecord | Failed AppRecord | app_id_canonical, validation_failures[], quarantine_reason | Written to quarantine queue, never to DataLake=Y |

### Shared Connectors (present in both SOC_USA and SOC_CAN configs)

These connectors must be declared identically in both config files. Any change to their
mapping triggers a mandatory dual-config review.

| Code | Name | Folders | Notes |
|------|------|---------|-------|
| C225334 | web_service_cc | raw/ | Primary app data; 82 REQ / 53 RESP fields; 100 schema paths |
| C103403 | pygdsa | raw/ | Double-parse (base64 → JSON); 4,438 CAN / 7,195 USA attrs; largest file driver |
| C238743 | database___uat_decision_variable_save | data/ | Authoritative decision source; also APR |
| C78098  | database___get | data/ | Both geos |
| C78449  | database___save | data/ | Archival/output |
| C215125 | database___extracts | data/ | Recommended_Credit_Limit (P2 preferred) |
| C224847 | database___file_transfer_save | data/ | Archival/doc management |

### USA-Only Connectors

| Code | Name | Wire format | Notes |
|------|------|-------------|-------|
| C1677939 | transunion_us_xml_v2_45 | HTTP+XML | USA bureau |
| C754889 | database___get_bureau_credentials | HTTP+text | CRED — scrub only (plain-text passwords) |

### CAN-Only Connectors

| Code | Name | Wire format | Notes |
|------|------|-------------|-------|
| C100810 | transunion_ca_fff_v4_0 | HTTP+FFF | Session 1 — BLOCKER |
| C161653 | equifax_ca_enterprise_oauth | HTTP+JSON | CRED — scrub only (OAuth) |
| C161796 | equifax_ca_sts_pi_fff | HTTP+FFF | Session 2 — BLOCKER |

### Score Slot Assignment

| Slot | Content | Geography | Population |
|------|---------|-----------|------------|
| score1 | Empirica Canada / Beacon (CAN) or FICO98 (USA) | Both | 5/8 apps in sample |
| score2 | SOC_RiskScore | Both | Null in all 8 sample apps |
| score3 | Custom Score | Both | Null in all 8 sample apps |
| score4–score14 | Unassigned | — | Must remain unassigned |

### Double-Encoded JSON Fields (require json_multiparse or base64_extract)

| Connector | Field | Encoding | Method |
|-----------|-------|----------|--------|
| C225334-RESP | DerivedApplicationRecord[0].Payload | Stringified JSON | json_double_parse |
| C225334-RESP | DecisionVariableRecord[0].Payload | Stringified JSON | json_double_parse |
| C238743-REQ | data.Decision sub-fields | Python repr | ast.literal_eval |
| C103403-RESP | Full payload | base64 → JSON | base64_extract |

---

## Engineer Sign-Off

**I confirm that I understand the core problem, the three hardest constraints, and the
definition of success without referring to this document.**

- [Yes] Problem framing is correct
- [Yes] All key design decisions and their rationale are accurate
- [Yes] Open questions list is complete
- [Yes] Risk register reflects known risks
- [Yes] Data model entities and shared-connector register are correct

**Engineer:** ________Mahendra Nayak_____________________ **Date:** ______23-06-2026_______


