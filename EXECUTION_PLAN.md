# EXECUTION_PLAN.md
## SOC Data Standardisation — Ingestion Pipeline
**Version:** v1.1 | **Date:** 2026-06-23 | **Status:** FINAL — Phase 4 gate amendments applied
**PBVI Phase:** 3 — Execution Planning (amended at Phase 4 gate)
**METHODOLOGY_VERSION:** v4.9

## Changelog
| Version | Date | Author | Change |
|---|---|---|---|
| v1.0 | 2026-06-23 | CD/Mahendra | Initial — Phase 3 output, 36 tasks across 9 sessions |
| v1.1 | 2026-06-23 | CD/Mahendra | Phase 4 gate amendments: A1 (unclassified file quarantine → TASK-1.3), A2 (TASK-1.5 added — dispatcher wiring), A3 (TASK-6.1 verification command fixed), A4 (workdir clearing → TASK-9.2), A5 (fixture placement → TASK-1.2). TASK-SCOPED invariant references updated to INVARIANTS.md v1.2. |

---

## Pre-Plan: Open Questions Status

| ID | Question | Build impact | Status |
|---|---|---|---|
| Q-FFF | FFF width spec for C100810 + C161796 | TASK-4.3, TASK-4.4 stubbed; implementation gated | OPEN — BLOCKER |
| Q1 | Production ZIP folder structure | Dispatcher tolerates unknown folders with alert | OPEN — go-live gate |
| Q2 | Call types beyond MPU | Config declares MPU only; unrecognised call_type alert wired | OPEN — go-live gate |
| Q3 | _test App ID treatment | Default: quarantine. Separate partition path stubbed with TODO | OPEN — go-live gate |
| Q4 | FF product CAN bureau routing | D-05 conditional form adopted; FF records tolerated without bureau | OPEN — go-live gate |
| Q5 | Declined applications in production | REQ-BL-001 / D-03 implemented; untested against real declines | OPEN — go-live gate |
| Q-PROD | PROD GDS environment confirmation | Pipeline runs against UAT only until resolved | OPEN — go-live gate |

---

## Session Overview

| Session | Name | Goal | Tasks | Est. Duration |
|---|---|---|---|---|
| S1 | Project Scaffold + Pipeline Spine | Repo structure, engine wired, ZIP unpack and manifest running; dispatcher wired | TASK-1.1 – TASK-1.5 | 1 day |
| S2 | Credential Scrub + Pre-Processing | All three credential connectors scrubbed; HTTP strip, GZIP detect, encoding normalise | TASK-2.1 – TASK-2.4 | 1 day |
| S3 | App ID Parsing + Session Assembly | Filename regex, canonical ID, geo dispatch, USA dedup, CAN session detection | TASK-3.1 – TASK-3.5 | 1–2 days |
| S4 | Connector Parse Strategies | All 13 connectors parsed; PyGDSA double-parse; FFF stub; XML; GDS envelope | TASK-4.1 – TASK-4.6 | 2 days |
| S5 | Field Mapping — SOC_USA | USA config + mapping sheet wired; all USA SDD paths resolved; decision extraction | TASK-5.1 – TASK-5.5 | 2–3 days |
| S6 | Field Mapping — SOC_CAN | CAN config + mapping sheet wired; CAN session merge; bureau attribution; FFF stub | TASK-6.1 – TASK-6.4 | 2 days |
| S7 | PII Tokenisation + ExtraColumns Scan | All PII fields tokenised; pattern-based ExtraColumns scan; zero-raw-PII assertion | TASK-7.1 – TASK-7.3 | 1–2 days |
| S8 | Validation Rules + Quarantine Queue | All REQ-VAL + REQ-BL rules; quarantine write; quarantine report | TASK-8.1 – TASK-8.4 | 1–2 days |
| S9 | Lineage + Output Write + End-to-End | Lineage complete; DataLake=Y write; end-to-end run against all 8 apps | TASK-9.1 – TASK-9.3 | 1 day |

**Total estimated duration:** ~12–16 days

---

## Session 1 — Project Scaffold + Pipeline Spine

**Session goal:** A runnable `run_pipeline()` call against the 8-app sample ZIP
returns an `AppRecord` list with no crashes. Manifest correctly lists all files with
folder/connector/direction classified. `dispatch_by_geo()` is wired into
`run_pipeline()` and correctly partitions files by geography.

**Integration check:**
```bash
python -c "
from scripts.ingest_lib import run_pipeline
records = run_pipeline(
    'tests/fixtures/soc_sample.zip',
    'assets/client_config.SOC_USA.yaml',
    'assets/field_mapping.SOC_USA.xlsx',
    'workdir/s1'
)
print(f'Records returned: {len(records)}')
assert len(records) > 0, 'No records returned'
print('S1 integration: PASS')
"
```

---

### TASK-1.1 — Repository Scaffold

**Description:**
Create the standard PBVI directory structure, copy `ingest_lib.py` from the project
skill into `scripts/`, place config templates into `assets/`, and place
`mapping_schema.md` into `references/`. Create `tests/fixtures/` and `tests/unit/`.
Create empty `client_config.SOC_USA.yaml` and `client_config.SOC_CAN.yaml` (unfilled).
Register all files in `PROJECT_MANIFEST.md`.

**CC prompt:**
```
Scaffold the soc-ingestion repository for a PBVI DATA_ACCELERATOR project.

Create directory structure:
  scripts/
  assets/
  references/
  tests/fixtures/
  tests/unit/
  tests/integration/
  docs/
  sessions/
  verification/
  discovery/
  tools/

Copy the following files:
  scripts/ingest_lib.py               — from project skill (existing engine)
  assets/client_config_template.yaml  — template only; do not fill
  references/mapping_schema.md        — read-only reference
  assets/client_config.SOC_USA.yaml   — create as empty YAML: # FILL IN TASK-3/5
  assets/client_config.SOC_CAN.yaml   — create as empty YAML: # FILL IN TASK-3/6

Create PROJECT_MANIFEST.md at repo root registering every created file.
Create README.md at repo root: project name, one-line description, phase status table.

Do not fill any <FILL:...> placeholders in config files.
Do not add any files not listed above.
```

**Test cases:**
- All directories exist
- `scripts/ingest_lib.py` is importable
- `PROJECT_MANIFEST.md` registers all files

**Verification command:**
```bash
python -c "from scripts.ingest_lib import run_pipeline; print('import OK')"
test -f assets/client_config.SOC_USA.yaml && echo "USA config present"
test -f assets/client_config.SOC_CAN.yaml && echo "CAN config present"
```

**Invariant enforcement:** GLOBAL invariants apply.
**Regression classification:** NOT-REGRESSION-RELEVANT — scaffold state only.

---

### TASK-1.2 — Sample ZIP Fixture + Manifest Smoke Test
*(Amendment A5 applied)*

**Description:**
Copy the 8-app sample ZIP to `tests/fixtures/soc_sample.zip`. Create
`tests/fixtures/README.md` and `.gitignore` entry. Write a unit test that calls
`unpack_zip()` + `build_manifest()` against the fixture.

**CC prompt:**
```
Write tests/unit/test_manifest.py.

The test must:
1. Call unpack_zip('tests/fixtures/soc_sample.zip', 'workdir/test_manifest')
2. Build a minimal ClientConfig stub covering folder_priority names
   (raw, data, audit, sdd, cc_extracts) and
   application_id.source = 'filename_tokens' with a permissive regex
3. Call build_manifest(root, cfg)
4. Assert: len(files) > 0
5. Assert: all(sf.folder is not None for sf in files)
6. Assert: empty cc_extracts/ folder is tolerated (no exception)

Create tests/fixtures/README.md containing:
  # Test Fixtures
  ## Required files (engineer-placed, not committed to Git)
  - soc_sample.zip — 8-app SOC sample ZIP. Place here before running Session 1.
    Do not commit this file. Source: SOC Phase 1 analysis package.
  ## CI/CD
  Inject soc_sample.zip from secure artifact store (TODO — team to configure).

Create tests/fixtures/.gitignore containing:
  *.zip

Use pytest. No mocking — call real functions against real fixture.
Do not modify ingest_lib.py.
```

**Test cases:**
- 8-app ZIP unpacks without error
- Manifest returns files from all non-empty folders
- Empty `cc_extracts/` tolerated

**Verification command:**
```bash
pytest tests/unit/test_manifest.py -v
```

**Invariant enforcement:** None task-scoped.
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-1.3 — Filename Parser: App ID, Geo, Connector, Sequence
*(Amendment A1 applied — unclassified file quarantine added)*

**Description:**
Implement `_classify_file()` for the SOC filename pattern. Extract: `version`,
`geo`, `debtor`, `dt`, `test` (optional), `connector`, `direction`, `sequence_id`.
Files where the regex produces no match must be flagged for quarantine — not silently
dropped.

**CC prompt:**
```
Implement _classify_file() in scripts/ingest_lib.py for the SOC filename token pattern.

SOC filename format:
  {version}_{geo}_{debtor}_{dt}[_test]_{connector}_{name}_{dir}_{ts}_{seq}_{step}.{ext}

Named regex groups required:
  version, geo (CAN|USA), debtor (\d{9}), dt (\d{14}),
  test (_test optional), connector (C\d+),
  direction (REQ|RESP case-insensitive), sequence_id (\d+)

After matching:
  sf.connector   = gd['connector']
  sf.direction   = gd.get('direction', '').upper()
  sf.sequence_id = gd.get('sequence_id')
  sf.app_id_raw  = gd['debtor'] + '_' + gd['dt']
                   (append '_test' literal if test group matched)
  sf.geography   = gd['geo']

AMENDMENT A1 — UNCLASSIFIED FILE QUARANTINE:
  Files where the filename regex produces no match must NOT be silently dropped.
  For any file where the regex returns no match:
      sf.app_id_raw = None
      sf.geography  = None
      log.warning('UNCLASSIFIED file=%s — will be quarantined by dispatcher', p.name)
  In dispatch_by_geo() (TASK-1.4), files with sf.geography=None and sf.app_id_raw=None
  are collected into the unroutable set and quarantined with 'filename_parse_failed' flag.

TASK-SCOPED INVARIANT — INV-07:
  app_id_raw must be built as a VARCHAR string concatenation. Do not cast debtor
  or dt to int at any point.

TASK-SCOPED INVARIANT — INV-10:
  If geo group is absent or not in ('CAN', 'USA'), do not attempt to infer
  geography from payload. Set sf.geography = None and log a WARNING.

Write tests/unit/test_classifier.py:
- Standard USA filename → all fields correct
- Standard CAN filename → all fields correct
- _test suffix filename → app_id_raw contains '_test', geography correct
- Unrecognised geo token → sf.geography = None, no exception
- Filename not matching pattern → sf.geography=None, sf.app_id_raw=None, warning logged
```

**Test cases:**
- Standard filenames parse correctly for both geos
- `_test` suffix detected
- Unrecognised geo → `sf.geography = None`
- No-match filename → `sf.app_id_raw = None`, warning emitted, no exception

**Verification command:**
```bash
pytest tests/unit/test_classifier.py -v
```

**Invariant enforcement:** INV-07 (VARCHAR), INV-10 (no geo inference).
**Regression classification:** HARNESS-CANDIDATE — directly tests INV-07 + INV-10.

---

### TASK-1.4 — Geo Dispatcher

**Description:**
Implement `dispatch_by_geo()`. Partition files into `{USA: [...], CAN: [...]}`.
Files with `sf.geography = None` (unclassified or unrecognised geo) are quarantined
before any pipeline stage.

**CC prompt:**
```
Implement dispatch_by_geo(files: list[SourceFile]) -> dict[str, list[SourceFile]]
in scripts/ingest_lib.py.

Logic:
  partitions = {'USA': [], 'CAN': []}
  unroutable = []
  for sf in files:
      if sf.geography in ('USA', 'CAN'):
          partitions[sf.geography].append(sf)
      else:
          unroutable.append(sf)

  For each file in unroutable:
      log.error('QUARANTINE geo=None/unrecognised file=%s — INV-10', sf.path.name)
      # Quarantine record written at pipeline level; dispatcher logs here

  return partitions

TASK-SCOPED INVARIANT — INV-10:
  Routing decisions must be explicit and deterministic. No default routing,
  silent fallback, or runtime inference is permitted. A file not matching
  'CAN' or 'USA' exactly is unroutable — do not attempt to recover or guess
  its geography.

Write tests/unit/test_dispatcher.py:
- 5 USA + 3 CAN files → correct partition counts
- File with geography=None → in unroutable log, not in either partition
- Empty file list → returns {'USA': [], 'CAN': []}
- Unclassified file (app_id_raw=None) → unroutable, not silently dropped
```

**Verification command:**
```bash
pytest tests/unit/test_dispatcher.py -v
```

**Invariant enforcement:** INV-10 (deterministic routing).
**Regression classification:** HARNESS-CANDIDATE — directly tests INV-10.

---

### TASK-1.5 — Wire dispatch_by_geo() into run_pipeline()
*(Amendment A2 — new task added at Phase 4 gate)*

**Description:**
Modify `run_pipeline()` to call `dispatch_by_geo()` after `build_manifest()` and
before `scrub_credentials()`. For each non-empty geography, load the matching config
and mapping sheet and run the processing loop. This closes the architecture–plan gap
identified at Phase 4: DD-07 (dispatcher) was a named architectural decision without
an implementation wiring task.

**CC prompt:**
```
Modify run_pipeline() in scripts/ingest_lib.py to call dispatch_by_geo() after
build_manifest() and before scrub_credentials().

New spine structure:
  files = build_manifest(root, cfg_base)
  geo_files = dispatch_by_geo(files)           # split by geography

  out: list[AppRecord] = []
  for geo, geo_file_set in geo_files.items():
      if not geo_file_set:
          continue
      geo_cfg = ClientConfig.load(
          f'assets/client_config.SOC_{geo}.yaml')
      geo_mapping = load_mapping_sheet(
          f'assets/field_mapping.SOC_{geo}.xlsx')

      scrubbed = scrub_credentials(geo_file_set, geo_cfg)   # I1 — FIRST
      for sf in geo_file_set:
          try:
              parse_file(sf, geo_cfg)
          except NotImplementedError as e:
              log.warning('parse pending %s: %s', sf.connector, e)
              _handle_fff_quarantine(sf, geo_cfg)            # see INV-13

      apps = group_by_app(geo_file_set, geo_cfg)
      blobs: list[dict] = []
      for rec in apps.values():
          rec.geography = geo
          merge_sessions(rec, geo_cfg)
          apply_mapping(rec, geo_mapping, geo_cfg)
          tokenise_pii(rec, geo_cfg)                         # I2 — before write
          assert_no_raw_pii(rec, geo_cfg)                    # I2 — proof
          build_lineage(rec, geo_cfg, str(zip_path), scrubbed, blobs)
          validate(rec, geo_cfg)                             # I3 — before write
          write_record(rec, geo_cfg)
          out.append(rec)
  return out

The original cfg/mapping_path parameters become cfg_base/mapping_base for
the USA config (default); CAN config loaded by convention as shown above.

TASK-SCOPED INVARIANT — INV-10:
  dispatch_by_geo() must be called before scrub_credentials(). Geography must be
  determined from the filename token only, never from payload content.

Write tests/integration/test_dispatcher_wiring.py:
- 8-app ZIP → dispatch produces non-empty USA and CAN partitions
- Each geo set processed with its matching config
- Unroutable files appear in quarantine report, not in output
- Integration check: assert total record count matches expected for sample ZIP
```

**Verification command:**
```bash
pytest tests/integration/test_dispatcher_wiring.py -v
```

**Invariant enforcement:** INV-10 (deterministic routing, wired before scrub).
**Regression classification:** HARNESS-CANDIDATE — end-to-end dispatcher integration.

---

## Session 2 — Credential Scrub + Pre-Processing

**Session goal:** `scrub_credentials()` against the 8-app sample files redacts all
three credential connectors. Post-scrub grep confirms zero raw credential strings in
any processed file.

**Integration check:**
```bash
pytest tests/integration/test_scrub.py -v
```

---

### TASK-2.1 — Credential Scrub: C161653 OAuth Header

**CC prompt:**
```
Implement credential scrub for connector C161653 in scripts/ingest_lib.py.

Target: HTTP Authorization header in raw/ payload.
Method: redact

TASK-SCOPED INVARIANT — INV-01 (pattern-based):
  Use regex: re.sub(r'(?i)(Authorization:\s*)\S+', r'\1[REDACTED]', payload_text)
  Do NOT match a hardcoded known token value.

TASK-SCOPED INVARIANT — INV-01 (scrub first):
  After scrub, overwrite sf.raw_bytes in-place so no downstream function can
  access the unredacted value.

Write tests/unit/test_scrub_c161653.py:
- 'Authorization: Bearer abc123' → '[REDACTED]'
- 'Authorization: Basic dXNlcjpwYXNz' → '[REDACTED]'
- No Authorization header → unchanged, no exception
- sf.raw_bytes after scrub contains no original token
```

**Verification command:** `pytest tests/unit/test_scrub_c161653.py -v`
**Invariant enforcement:** INV-01 (scrub first + pattern-based).
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-2.2 — Credential Scrub: C754889 Plain-Text Passwords

**CC prompt:**
```
Implement credential scrub for connector C754889.

Target: username and password fields in request body.
Method: null_out

TASK-SCOPED INVARIANT — INV-01 (pattern-based):
  Field patterns (case-insensitive): password, passwd, pwd, pass
  Do not hardcode a known password value.

TASK-SCOPED INVARIANT — INV-01 (scrub first):
  Overwrite sf.raw_bytes in-place after scrub.

Write tests/unit/test_scrub_c754889.py:
- 'password=abc123' → value nulled
- 'Password=ABC' → case-insensitive match, nulled
- 'username=admin&pwd=secret' → both nulled
- No credential fields → unchanged
```

**Verification command:** `pytest tests/unit/test_scrub_c754889.py -v`
**Invariant enforcement:** INV-01.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-2.3 — Credential Scrub: C103403 Bearer Token

**CC prompt:**
```
Implement credential scrub for connector C103403. Two scrub locations:

1. HTTP Authorization header:
   re.sub(r'(?i)(Authorization:\s*)\S+', r'\1[SCRUBBED]', payload_text)

2. JSON body credential field (after HTTP envelope strip):
   Locate key matching r'(?i)(bearer.?token|access.?token|api.?key)'
   Replace value with '[SCRUBBED]'.

TASK-SCOPED INVARIANT — INV-01 (pattern-based):
  Both locations use pattern-based detection. No hardcoded token strings.

TASK-SCOPED INVARIANT — INV-01 (scrub first):
  Both scrubs must complete before base64 decode begins.
  Overwrite sf.raw_bytes in-place.

Write tests/unit/test_scrub_c103403.py:
- HTTP header with Bearer → [SCRUBBED]
- JSON body with 'bearer_token' key → value scrubbed
- JSON body with 'access_token' key → value scrubbed
- No credential fields → unchanged
```

**Verification command:** `pytest tests/unit/test_scrub_c103403.py -v`
**Invariant enforcement:** INV-01.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-2.4 — HTTP Envelope Strip, GZIP Detect, Encoding Normalise

**CC prompt:**
```
Verify and extend pre-processing functions in scripts/ingest_lib.py:

1. http_envelope_strip: confirm CRLFCRLF split. Test: headers → body only.
2. maybe_gunzip: confirm magic byte b'\x1f\x8b'. Test: gzipped → decompressed.
   Note: no GZIP in 8-app sample. Test with synthetic gzipped content.
3. normalise_encoding(body, accept, target='utf-8'):
   Try UTF-8 first. If UnicodeDecodeError, try ISO-8859-1. Re-encode to UTF-8.
   If both fail, raise ValueError with connector code.

Write tests/unit/test_preprocess.py covering all three functions.
```

**Verification command:** `pytest tests/unit/test_preprocess.py -v`
**Invariant enforcement:** None task-scoped.
**Regression classification:** REGRESSION-RELEVANT.

---

## Session 3 — App ID Parsing + Session Assembly

**Session goal:** `group_by_app()` produces the correct number of AppRecord objects.
CAN records have `multi_session_incomplete` correctly set or cleared. USA retry
record is deduped. Unclassified files produce quarantine records.

**Integration check:**
```bash
pytest tests/integration/test_session_assembly.py -v
```

---

### TASK-3.1 — Canonical App ID + _test Isolation

**CC prompt:**
```
Implement _canonicalise_app_id() in scripts/ingest_lib.py.

If app_id_raw ends with '_test':
    app_id_canonical = app_id_raw[:-5]
    lineage['app_id_raw_had_test_suffix'] = True
else:
    app_id_canonical = app_id_raw

TASK-SCOPED INVARIANT — INV-09:
  A record with app_id_raw containing '_test' must be quarantined.
  Set rec.quarantined = True and rec.lineage['test_quarantine'] = True.
  Do NOT write _test records to DataLake=Y under any circumstance.
  # TODO(Q3): when separate_partition is confirmed, implement partition
  # routing here instead of quarantine.

TASK-SCOPED INVARIANT — INV-07 / D-10:
  app_id_canonical and app_id_raw are both VARCHAR strings. No numeric coercion.
  Both must be preserved in lineage.

Write tests/unit/test_app_id.py:
- Standard app_id_raw → canonical unchanged, no test flag
- _test suffix → canonical stripped, test flag set, quarantined
- app_id_raw preserved in lineage after canonicalisation
```

**Verification command:** `pytest tests/unit/test_app_id.py -v`
**Invariant enforcement:** INV-09, INV-07, D-10.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-3.2 — group_by_app() with Composite Dedup Key

**CC prompt:**
```
Implement group_by_app() in scripts/ingest_lib.py.

Key = app_id_canonical (VARCHAR).
USA retry deduplication: if two SourceFiles have identical
(connector, direction, transaction_id, sequence_id), keep latest timestamp.

TASK-SCOPED INVARIANT — D-02:
  Before finalising a group, check that all files share the same EcsDebtorNumber
  (debtor_number component of app_id_raw). If COUNT(DISTINCT EcsDebtorNumber) > 1:
  rec.quarantined = True
  rec.validation_failures.append('D-02-cross-session-identity-mismatch')

Write tests/unit/test_grouping.py:
- 5 USA + 3 CAN distinct App IDs → 8 AppRecord objects
- USA retry: two files same App ID + sequence → 1 SourceFile retained (latest)
- Cross-debtor mismatch → AppRecord quarantined with D-02 failure
```

**Verification command:** `pytest tests/unit/test_grouping.py -v`
**Invariant enforcement:** D-02.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-3.3 — CAN Session Detection (Connector Presence)
*(INV-11 removed; protection embedded here as implementation guidance)*

**CC prompt:**
```
Implement CAN session detection in merge_sessions() in scripts/ingest_lib.py.

For AppRecords where rec.geography == 'CAN':

  session1_present = any(sf.connector == 'C100810' for sf in rec.files)
  session2_present = any(sf.connector in ('C161653', 'C161796') for sf in rec.files)
  bureau_eval_indicated = session1_present or session2_present

  if bureau_eval_indicated:
      if not (session1_present and session2_present):
          rec.lineage['multi_session_incomplete'] = True
          rec.quarantined = True
          rec.validation_failures.append('REQ-VAL-003')

  Label sessions in lineage:
      rec.lineage['can_session_1_connectors'] = ['C100810'] if present
      rec.lineage['can_session_2_connectors'] = ['C161653' or 'C161796'] if present

IMPLEMENTATION GUIDANCE (from removed INV-11):
  CAN session detection MUST use connector presence only.
  sequence_id MUST NOT be read or compared during CAN session detection.
  Do not access sf.sequence_id in this function for CAN records.
  Rationale: Phase 1 analysis confirmed sequence_id is unreliable for session
  identity — USA retry at seq=80 has two data sessions representing retry,
  not two bureau sessions.

TASK-SCOPED INVARIANT — D-05:
  A CAN AppRecord with bureau_eval_indicated=True and only one session present
  must be quarantined. Do not write a partial CAN bureau record.

Write tests/unit/test_can_sessions.py:
- CAN with C100810 + C161796 → both sessions detected, not quarantined
- CAN with C100810 only → multi_session_incomplete=True, quarantined
- CAN with no bureau connectors → bureau_eval_indicated=False, not quarantined
- Mock sf.sequence_id with sentinel; assert it is never read during CAN detection
```

**Verification command:** `pytest tests/unit/test_can_sessions.py -v`
**Invariant enforcement:** D-05.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-3.4 — CAN Session Ordering Check (D-01)

**CC prompt:**
```
Implement CAN session ordering check in merge_sessions() — runs after TASK-3.3.
Only when both sessions present.

  tu_ts  = max(sf.datetime for sf in rec.files if sf.connector == 'C100810')
  efx_ts = max(sf.datetime for sf in rec.files if sf.connector in ('C161653','C161796'))

  if efx_ts <= tu_ts:
      rec.lineage['session_order_anomaly'] = True
      rec.validation_failures.append('REQ-BL-002')
      # soft-warn — do NOT quarantine on ordering anomaly alone

TASK-SCOPED INVARIANT — D-01:
  IF geography=CAN AND both sessions present THEN EFX.timestamp > TU.timestamp.
  Violation is a soft-warn (REQ-BL-002). Record the anomaly; do not block the write.

Write tests/unit/test_can_ordering.py:
- EFX later than TU → no anomaly flag
- EFX earlier than TU → session_order_anomaly=True, REQ-BL-002 in failures
- Equal timestamps → session_order_anomaly=True (strictly greater required)
```

**Verification command:** `pytest tests/unit/test_can_ordering.py -v`
**Invariant enforcement:** D-01.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-3.5 — EcsDebtorNumber Cross-Session Consistency (D-02 payload enforcement)

**CC prompt:**
```
Add EcsDebtorNumber payload check to merge_sessions() for CAN records.

After connector payloads are parsed, extract EcsDebtorNumber from:
  C225334-REQ: record.EcsDebtorNumber
  C103403-RESP: attributes['EcsDebtorNumber'] (after double-parse)
  data/ tier: data.EcsDebtorNumber

If len(distinct_values) > 1:
    rec.quarantined = True
    rec.validation_failures.append('D-02-payload-debtor-mismatch')
    log.error('EcsDebtorNumber mismatch AppID=%s values=%s',
              rec.app_id_canonical, distinct_values)

TASK-SCOPED INVARIANT — D-02:
  COUNT(DISTINCT EcsDebtorNumber) across all sessions = 1. Any mismatch = quarantine.

Write tests/unit/test_debtor_consistency.py:
- All sessions same debtor → no quarantine
- Two sessions different debtors → quarantined, D-02 failure
- No debtor in payloads → no quarantine (graceful skip)
```

**Verification command:** `pytest tests/unit/test_debtor_consistency.py -v`
**Invariant enforcement:** D-02.
**Regression classification:** HARNESS-CANDIDATE.

---

## Session 4 — Connector Parse Strategies

**Session goal:** All 13 SOC connectors have a registered parse strategy. Running
`parse_file()` against each type returns a non-None payload or a documented stub.

**Integration check:**
```bash
pytest tests/integration/test_parse_strategies.py -v
```

---

### TASK-4.1 — GDS Envelope JSON Strategy (data/ tier)

**CC prompt:**
```
Verify gds_envelope_json strategy for data/ tier connectors:
C78098, C78449, C215125, C238743, C224847.

Strategy returns obj.get('data', obj).

TASK-SCOPED INVARIANT — D-04 (C238743 only):
  When parsing C238743-RESP, do not extract or pre-populate any decision field.
  Decision extraction happens in TASK-5.2. Parsing only makes the payload available.

Write tests/unit/test_parse_gds_envelope.py:
- GDS envelope with data{} → data{} contents returned
- GDS envelope without data{} → full object returned
- Malformed JSON → json.JSONDecodeError propagated
- C238743-RESP parsed → rec.record['decision'] is NOT set by this function
```

**Verification command:** `pytest tests/unit/test_parse_gds_envelope.py -v`
**Invariant enforcement:** D-04 (C238743 parse must not pre-populate decision).
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-4.2 — XML Strategy: C1677939 TransUnion USA

**CC prompt:**
```
Verify xml_dict strategy for C1677939.

Steps: HTTP envelope strip → maybe_gunzip → xmltodict.parse → _strip_ns()

NOTE: _strip_ns() is recursive. Add a recursion depth guard for production
hardening (TODO comment accepted — depth limit implementation deferred):
# TODO(production-hardening): add max_depth parameter to _strip_ns() to
# prevent stack overflow on pathologically nested XML. Real GDS payloads
# are shallow; this is a production safety net only.

Write tests/unit/test_parse_xml.py using tests/fixtures/transunion_sample.xml
(create minimal synthetic XML with namespace prefixes):
- XML with ns2: prefixes → prefixes stripped
- Nested namespace → all levels stripped
- Malformed XML → ExpatError propagated
```

**Verification command:** `pytest tests/unit/test_parse_xml.py -v`
**Invariant enforcement:** None task-scoped.
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-4.3 — FFF Strategy Stub: C100810 (TransUnion CAN)

**CC prompt:**
```
Implement FFF parse strategy stub for C100810.

@strategy("fff")
def _parse_fff(sf, cfg):
    # TODO(Q-FFF): implement when FFF width specification delivered by SOC client.
    raise NotImplementedError(
        f"FFF parse not implemented — connector {sf.connector}. "
        "Awaiting FFF layout spec from SOC client (Q-FFF)."
    )

Implement _handle_fff_quarantine(sf, rec):
    sf.payload = None
    rec.lineage['fff_parse_blocked'] = True
    rec.validation_failures.append('fff_parse_blocked')
    rec.quarantined = True

Wire into run_pipeline() NotImplementedError catch for fff wire_format connectors.

TASK-SCOPED INVARIANT — INV-13:
  Required bureau evidence may not silently degrade into a valid output record.
  FFF parse failure = hard quarantine. Silent skip is not permitted.

Write tests/unit/test_parse_fff_stub.py:
- C100810 file → NotImplementedError raised and caught, record quarantined
- fff_parse_blocked in lineage
- record.quarantined = True
```

**Verification command:** `pytest tests/unit/test_parse_fff_stub.py -v`
**Invariant enforcement:** INV-13.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-4.4 — FFF Strategy Stub: C161796 (Equifax CAN)

**CC prompt:**
```
Implement FFF parse strategy stub for C161796 (equifax_ca_sts_pi_fff).
Follow exactly the same pattern as TASK-4.3.

TASK-SCOPED INVARIANT — INV-13:
  FFF parse failure on C161796 is a hard quarantine. Identical to C100810.

Write tests/unit/test_parse_fff_c161796.py — same structure as TASK-4.3.
```

**Verification command:** `pytest tests/unit/test_parse_fff_c161796.py -v`
**Invariant enforcement:** INV-13.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-4.5 — PyGDSA Double-Parse: C103403

**CC prompt:**
```
Implement C103403 double-parse pipeline:
1. http_envelope_strip
2. maybe_gunzip
3. json.loads → outer_json
4. base64.b64decode each segment + json.loads → flat attrs dict
5. sf.payload = attrs
6. Record base64_blobs_extracted in lineage

Assert credential scrub complete before step 1:
  assert not re.search(r'(?i)Authorization:\s*Bearer\s+\S+',
                       sf.raw_bytes.decode('utf-8', errors='replace')), \
      "INV-01: C103403 credential not scrubbed before double-parse"

Implementation guidance (not an invariant — from D-11 reclassification):
  attr_count = len(sf.payload)
  if attr_count < 100:
      log.warning('REQ-BL-004: C103403 attr_count=%d < 100', attr_count)
      rec.validation_failures.append('REQ-BL-004')
      # soft-warn only — do NOT quarantine

Write tests/unit/test_parse_pygdsa.py:
- Synthetic base64 JSON blob → decoded correctly, attr_count > 100
- attr_count < 100 → REQ-BL-004 in failures, not quarantined
- Non-base64 content → binascii.Error propagated
- Bearer token present before decode → assertion fires
```

**Verification command:** `pytest tests/unit/test_parse_pygdsa.py -v`
**Invariant enforcement:** INV-01 (credential pre-check).
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-4.6 — Credential Discard: C161653

**CC prompt:**
```
Confirm credential_discard strategy for C161653.

@strategy("credential_discard")
def _parse_cred(sf, cfg): return None

Add C161653 to client_config.SOC_CAN.yaml:
  is_credential: true
  parse_strategy: credential_discard

TASK-SCOPED INVARIANT — D-06:
  A credential connector (is_credential=true) must never produce a payload.
  Returning None is the required behaviour.

Write tests/unit/test_credential_discard.py:
- C161653 → parse_file() returns None, sf.payload = None
- C161653 NOT in any field mapping source locator
```

**Verification command:** `pytest tests/unit/test_credential_discard.py -v`
**Invariant enforcement:** D-06.
**Regression classification:** REGRESSION-RELEVANT.

---

## Session 5 — Field Mapping: SOC_USA

**Session goal:** `apply_mapping()` against USA AppRecords resolves all Standard
Schema paths with `P` status. Decision extracted from C238743-RESP. Source priority
resolution is deterministic.

**Integration check:**
```bash
pytest tests/integration/test_mapping_usa.py -v
```

---

### TASK-5.1 — SOC_USA Config + Mapping Sheet Scaffold

**CC prompt:**
```
Validate client_config.SOC_USA.yaml: syntactically valid YAML; all connectors
registered with valid parse_strategy entries.

Connectors with is_credential: false:
  C225334, C78098, C78449, C103403, C1677939, C215125, C238743, C224847

Connectors with is_credential: true:
  C754889

Report any <FILL:...> placeholders as gaps for the engineer. Do not fill them.
```

**Verification command:**
```bash
python -c "
import yaml
cfg = yaml.safe_load(open('assets/client_config.SOC_USA.yaml'))
print('YAML OK')
print([c['code'] for c in cfg.get('connectors', [])])
"
```

**Invariant enforcement:** D-12 (source priority declared in config).
**Regression classification:** NOT-REGRESSION-RELEVANT.

---

### TASK-5.2 — Decision Extraction: C238743-RESP

**CC prompt:**
```
Implement decision extraction from C238743-RESP in apply_mapping().

Decision path: C238743 / data/ / RESP / data.Decision.decision
APR path:      C238743 / data/ / RESP / data.Decision.interestrate

Resolution logic:
  1. Find SourceFile: connector='C238743', direction='RESP'
  2. If found and non-None payload:
         val = _get_nested(sf.payload, 'Decision.decision')
         if val: _set_path(rec.record, 'system.application.decision', val)
         else: rec.lineage['decision_missing'] = True; append 'REQ-VAL-006'
  3. If no C238743-RESP: decision_missing=True, REQ-VAL-006

TASK-SCOPED INVARIANT — D-04:
  Under no circumstance may this function read from audit/ folder for decision.
  Guard: if sf.folder == 'audit': continue
  The only connector code that may set rec.record['decision'] is 'C238743'.

Write tests/unit/test_decision_extraction.py:
- C238743-RESP decision='APP' → system.application.decision='APP'
- C238743-RESP absent → decision_missing=True
- Audit layer present with decision → ignored (D-04 guard fires)
```

**Verification command:** `pytest tests/unit/test_decision_extraction.py -v`
**Invariant enforcement:** D-04.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-5.3 — Score Slot Mapping + Slot Bounding

**CC prompt:**
```
Implement score slot mapping for USA records.

score1: C225334-RESP record.FICO (string_to_numeric) → secondary: audit score1
score2: C225334-RESP record.SOC_RiskScore (null in sample — map if present)
score3: C225334-RESP record.CustomScore (null in sample — map if present)

Post-mapping slot bounding check (implementation guidance — INV-08 removed,
protection retained here):
  for slot in range(4, 15):
      key = f'system.application.scores.score{slot}'
      if _get_path(rec.record, key) is not None:
          raise ValueError(f'Score slot {slot} populated for SOC — mapping error')

Write tests/unit/test_score_mapping.py:
- FICO='680' → score1=680 (int after numeric transform)
- score4 populated by test injection → ValueError raised
- score2, score3 null → null in output (graceful)
```

**Verification command:** `pytest tests/unit/test_score_mapping.py -v`
**Invariant enforcement:** None INVARIANTS.md entry; slot guard is implementation guidance.
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-5.4 — Dec_Reasons Pipe-Split + Decline Completeness (D-03)

**CC prompt:**
```
Implement Dec_Reasons mapping.

Source: C225334-RESP record.Dec_Reasons (pipe-delimited)
Target: system.application.decisionSummary.reasonCodes[]
Transform: split_on_delim (delimiter='|')

Also map:
  record.Dec_Description → decisionSummary.description
  record.Stipulations    → decisionSummary.stipulations[] (same split)

TASK-SCOPED INVARIANT — D-03:
  After decision + reason code mapping:
  if decision == 'DECLINED' and len(reasonCodes) == 0:
      rec.validation_failures.append('REQ-BL-001')
      rec.lineage['reason_codes_missing'] = True
      # soft-warn — do NOT quarantine for missing reason codes alone

Write tests/unit/test_dec_reasons.py:
- 'CODE1|CODE2|CODE3' → ['CODE1','CODE2','CODE3']
- decision=DECLINED, codes=[] → REQ-BL-001 in failures
- decision=APPROVED, codes=[] → no REQ-BL-001
```

**Verification command:** `pytest tests/unit/test_dec_reasons.py -v`
**Invariant enforcement:** D-03.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-5.5 — Source Priority Resolution + D-12 Enforcement

**CC prompt:**
```
Implement resolve_source() in full.

Walk sources PRIMARY → SECONDARY → TERTIARY.
For each: find matching SourceFile by connector+folder+direction;
call _get_nested(sf.payload, src['path']); if non-null return; else continue.

TASK-SCOPED INVARIANT — D-12:
  Source priority is determined solely by tier order in the MappingRow.
  Do NOT implement any runtime heuristic that selects a lower-priority source
  because higher-priority has 'more complete' data. Standard fallback (null →
  try next tier) is the only permitted runtime source selection mechanism.

Write tests/unit/test_source_priority.py:
- PRIMARY non-null → PRIMARY used, SECONDARY not accessed
- PRIMARY null → SECONDARY used
- All null → None returned
- 'Richer' PRIMARY injected after SECONDARY selected → SECONDARY still used
```

**Verification command:**
```bash
pytest tests/unit/test_source_priority.py -v
pytest tests/integration/test_mapping_usa.py -v
```

**Invariant enforcement:** D-12.
**Regression classification:** HARNESS-CANDIDATE.

---

## Session 6 — Field Mapping: SOC_CAN

**Session goal:** `apply_mapping()` against CAN AppRecords resolves all Standard
Schema paths in `field_mapping.SOC_CAN.xlsx`. Bureau data segmented by provider.
FFF connectors quarantined, not silently skipped.

**Integration check:**
```bash
pytest tests/integration/test_mapping_can.py -v
```

---

### TASK-6.1 — SOC_CAN Config + Mapping Sheet Scaffold
*(Amendment A3 applied — validate_configs.py replaced with inline Python)*

**CC prompt:**
```
Validate client_config.SOC_CAN.yaml.

CAN-specific checks:
  C100810: is_credential=false, parse_strategy='fff'
  C161653: is_credential=true, parse_strategy='credential_discard'
  C161796: is_credential=false, parse_strategy='fff'

Do not fill any <FILL:...> placeholders.
```

**Verification command:**
*(Amendment A3 — inline Python replaces validate_configs.py reference)*
```bash
python -c "
import yaml
usa = yaml.safe_load(open('assets/client_config.SOC_USA.yaml'))
can = yaml.safe_load(open('assets/client_config.SOC_CAN.yaml'))
shared = {'C225334','C103403','C238743','C78098','C78449','C215125','C224847'}
usa_map = {c['code']: c for c in usa.get('connectors', [])}
can_map = {c['code']: c for c in can.get('connectors', [])}
errors = []
for code in shared:
    if code in usa_map and code in can_map:
        for field in ('parse_strategy', 'wire_format'):
            if usa_map[code].get(field) != can_map[code].get(field):
                errors.append(f'{code}.{field}: USA={usa_map[code].get(field)} vs CAN={can_map[code].get(field)}')
if errors:
    print('SYNC ERRORS:', errors); exit(1)
else:
    print('Shared connector sync: PASS')
"
```

**Invariant enforcement:** D-12 (source priority consistent across both configs).
**Regression classification:** NOT-REGRESSION-RELEVANT.

---

### TASK-6.2 — CAN Bureau Attribution: D-09

**CC prompt:**
```
Implement CAN bureau data segmentation.

C100810 fields → rec.record['bureauData']['transunion'][field_name]
C161796/C161653 fields → rec.record['bureauData']['equifax'][field_name]
lineage: rec.lineage['bureau_providers'] = ['transunion', 'equifax'] (or subset)

TASK-SCOPED INVARIANT — D-09:
  Every bureau-derived field must carry provider attribution.
  Assert after apply_mapping():
  - No bureau field at bureauData root without a provider sub-key
  - rec.lineage['bureau_providers'] non-empty for any record with bureau files present

Write tests/unit/test_can_bureau_attribution.py:
- C100810 fields → under bureauData.transunion
- C161796 fields → under bureauData.equifax
- Field at bureauData root (injected) → assertion fails (D-09 guard)
```

**Verification command:** `pytest tests/unit/test_can_bureau_attribution.py -v`
**Invariant enforcement:** D-09.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-6.3 — Double-Encoded JSON Fields

**CC prompt:**
```
Implement json_double_parse and ast_literal_eval transforms.

1. C225334-RESP DerivedApplicationRecord[0].Payload → json_double_parse
   → rec.extra_columns['SOC_derived_application']
2. C225334-RESP DecisionVariableRecord[0].Payload → json_double_parse
   → rec.extra_columns['SOC_decision_variable']
3. C238743-REQ data.Decision sub-fields → ast_literal_eval
   → rec.extra_columns['SOC_decision_req']

SECURITY: Never use eval(). Use ast.literal_eval() exclusively.
ast.literal_eval raises ValueError for non-literal expressions — let it propagate.

Write tests/unit/test_double_parse.py:
- Stringified JSON → parsed correctly
- Python repr dict via ast.literal_eval → parsed correctly
- eval() not called anywhere (grep assertion in test)
- Malformed inner JSON → json.JSONDecodeError propagated
```

**Verification command:**
```bash
pytest tests/unit/test_double_parse.py -v
grep -n "eval(" scripts/ingest_lib.py | grep -v "ast.literal_eval" | grep -v "#" \
  && echo "FAIL: bare eval() found" || echo "No bare eval() — PASS"
```

**Invariant enforcement:** IC-4 / D-06 (no credential leakage through eval).
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-6.4 — ExtraColumns Group Registration

**CC prompt:**
```
Register ExtraColumns groups in both configs:
  SOC_pygdsa_attributes    — C103403
  SOC_derived_application  — C225334
  SOC_decision_variable    — C225334
  SOC_decision_req         — C238743

Implement extra_columns write in apply_mapping():
  Unmapped fields → rec.extra_columns[group_name][field_name]
  Never to rec.record root.

Write tests/unit/test_extra_columns.py:
- Unmapped field → in extra_columns, not in rec.record
- All groups present after mapping
- rec.record root has no unexpected top-level keys
```

**Verification command:** `pytest tests/unit/test_extra_columns.py -v`
**Invariant enforcement:** D-13 (extra_columns separate from core schema).
**Regression classification:** REGRESSION-RELEVANT.

---

## Session 7 — PII Tokenisation + ExtraColumns Scan

**Session goal:** All PII fields tokenised. `assert_no_raw_pii()` passes against all
8 output AppRecords.

**Integration check:**
```bash
pytest tests/integration/test_pii.py -v
```

---

### TASK-7.1 — Static PII Field Tokenisation

**CC prompt:**
```
Implement tokenise_pii() for all static PII fields.

Methods:
  pseudonym_reversible: 'TOK_' + sha256(value)[:16]  (vault stub — TODO(team))
  oneway_hash:          sha256(value).hexdigest()
  year_only:            keep year component only from date string
  scrub_never_store:    remove field entirely from rec.record

TASK-SCOPED INVARIANT — INV-02 / D-07:
  tokenise_pii() must be called and complete before write_record().
  After completion, assert no field in pii.fields retains its raw value.

PII fields: firstName, lastName, dateOfBirth, SSN/SIN,
            address (street, city, postal), phoneNumber, emailAddress

Write tests/unit/test_tokenise.py:
- firstName → 'TOK_' + hash
- SSN → SHA-256 hex
- DOB → year only
- scrub_never_store field → removed from rec.record
- All fields tokenised → raw values absent
```

**Verification command:** `pytest tests/unit/test_tokenise.py -v`
**Invariant enforcement:** INV-02, D-07.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-7.2 — ExtraColumns PII Pattern Scan

**CC prompt:**
```
Implement _scan_extra_columns_for_pii() — second enforcement path for INV-02.

Patterns (compile at module level):
  _PII_PATTERNS = {
      'email': re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}'),
      'phone': re.compile(r'(?:\+?1[\s\-.]?)?\(?\d{3}\)?[\s\-.]?\d{3}[\s\-.]?\d{4}'),
      'ssn':   re.compile(r'\b\d{3}[\-\s]?\d{2}[\-\s]?\d{4}\b'),
      'sin':   re.compile(r'\b\d{3}[\-\s]?\d{3}[\-\s]?\d{3}\b'),
      'fein':  re.compile(r'\b\d{2}[\-]?\d{7}\b'),
  }

Scan field VALUES (not names) across all extra_columns entries.
Match → tokenise with 'TOK_EC_' + sha256(val)[:16]
Record in lineage: extra_columns_pii_found[{key, pattern}]

TASK-SCOPED INVARIANT — INV-02 (second enforcement path):
  Scan must run on EVERY AppRecord. Pattern-based on values, not field names.

Write tests/unit/test_ec_pii_scan.py:
- Value='test@example.com' → tokenised
- Value='555-123-4567' → tokenised
- Value='no pii here' → unchanged
- Field NAME='email' but value has no PII → unchanged (value-scan confirmed)
```

**Verification command:** `pytest tests/unit/test_ec_pii_scan.py -v`
**Invariant enforcement:** INV-02 (ExtraColumns enforcement path).
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-7.3 — Zero-Raw-PII Assertion

**CC prompt:**
```
Implement assert_no_raw_pii() — write gate.

blob = json.dumps(rec.record) + json.dumps(rec.extra_columns)
for pattern_name, pattern in _PII_PATTERNS.items():
    match = pattern.search(blob)
    if match:
        raise RuntimeError(
            f'INV-02/D-07 VIOLATION: raw {pattern_name} PII in '
            f'AppID={rec.app_id_canonical}. '
            f'Context: ...{blob[max(0,match.start()-20):match.end()+20]}...'
        )

In run_pipeline() catch RuntimeError:
    rec.quarantined = True
    rec.validation_failures.append('REQ-VAL-007')
    log.critical('RAW PII DETECTED %s', rec.app_id_canonical)
    # do NOT re-raise — pipeline continues to next record

TASK-SCOPED INVARIANT — INV-02:
  This is a write gate, not a log step. Record that triggers it is quarantined.

Write tests/unit/test_zero_pii.py:
- All PII tokenised → no RuntimeError
- Raw email injected post-tokenisation → RuntimeError raised, quarantined
- RuntimeError caught → REQ-VAL-007 in validation_failures
```

**Verification command:** `pytest tests/unit/test_zero_pii.py -v`
**Invariant enforcement:** INV-02, D-07.
**Regression classification:** HARNESS-CANDIDATE.

---

## Session 8 — Validation Rules + Quarantine Queue

**Session goal:** All REQ-VAL and REQ-BL rules implemented. Valid records pass;
structurally invalid inputs quarantine correctly.

**Integration check:**
```bash
pytest tests/integration/test_validation.py -v
```

---

### TASK-8.1 — Hard Quarantine Rules: REQ-VAL-001 through REQ-VAL-008

**CC prompt:**
```
Implement remaining validation rules using @rule() decorator.
Already present: REQ-VAL-001, 002, 005, 007, 008.

Add:

@rule("REQ-VAL-003")
def _can_two_sessions(rec, cfg):
    if rec.geography != 'CAN': return True
    bureau_indicated = rec.lineage.get('can_session_1_connectors') or \
                       rec.lineage.get('can_session_2_connectors')
    if not bureau_indicated: return True   # FF product — not subject
    return not rec.lineage.get('multi_session_incomplete', False)

@rule("REQ-VAL-004")
def _has_bureau(rec, cfg):
    has = any(sf.connector in ('C100810','C161796','C1677939') for sf in rec.files)
    if not has: rec.lineage['has_bureau_data'] = False
    return True   # soft-warn only

@rule("REQ-VAL-006")
def _decision_present(rec, cfg):
    decision = rec.record.get('system',{}).get('application',{}).get('decision')
    return decision is not None or rec.lineage.get('decision_missing', False)

hard_quarantine: REQ-VAL-001, 002, 003, 005, 007, 008
soft_warn:       REQ-VAL-004, 006

TASK-SCOPED INVARIANT — INV-03:
  validate() executes before write_record(). Hard-quarantine failures block write.

TASK-SCOPED INVARIANT — D-05:
  REQ-VAL-003 enforces the conditional form — only applies when bureau connectors
  are present (bureau_eval_indicated). FF product records not subject to this rule.

Write tests/unit/test_validation_rules.py covering pass and fail for each rule.
```

**Verification command:** `pytest tests/unit/test_validation_rules.py -v`
**Invariant enforcement:** INV-03, D-05.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-8.2 — Business Logic Rules: REQ-BL-001 through REQ-BL-005

**CC prompt:**
```
Implement REQ-BL-001 through REQ-BL-005.
All are soft_warn_rules (not hard_quarantine_rules).

REQ-BL-001: reads lineage.reason_codes_missing → from D-03 (TASK-5.4)
REQ-BL-002: reads lineage.session_order_anomaly → from D-01 (TASK-3.4)
REQ-BL-003: reads validation_failures for 'D-02-*' → from D-02 (TASK-3.2/3.5)

REQ-BL-004: attr_count = len(extra_columns.get('SOC_pygdsa_attributes', {}))
             if 0 < attr_count < 100: lineage['pygdsa_parse_partial']=True; return False
             return True

REQ-BL-005: prod_info = rec.record...get('productInformation', [])
             if not prod_info: lineage['product_info_incomplete']=True; return False
             return True

Write tests/unit/test_bl_rules.py covering pass and fail for each rule.
```

**Verification command:** `pytest tests/unit/test_bl_rules.py -v`
**Invariant enforcement:** D-01 (BL-002), D-02 (BL-003), D-03 (BL-001).
**Regression classification:** REGRESSION-RELEVANT.

---

### TASK-8.3 — Quarantine Queue Write

**CC prompt:**
```
Implement quarantine write path in write_record().

If rec.quarantined:
    quarantine_record = {
        'app_id_canonical': rec.app_id_canonical,
        'app_id_raw':       rec.app_id_raw,
        'geography':        rec.geography,
        'quarantine_reason': rec.validation_failures,
        'lineage':          rec.lineage,
        'record_partial':   rec.record,
    }
    path = Path(workdir) / 'quarantine' / f'{rec.app_id_canonical}.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(quarantine_record, indent=2))
    log.error('QUARANTINE %s → %s', rec.app_id_canonical, rec.validation_failures)
    return

TASK-SCOPED INVARIANT — INV-09:
  DataLake=Y write path is unreachable for rec.quarantined=True.
  Add: assert not rec.quarantined before DataLake write stub.

TASK-SCOPED INVARIANT — D-08:
  Quarantine write uses app_id_canonical as filename key — one file per canonical
  App ID per run.

Write tests/unit/test_quarantine_write.py:
- Quarantined → JSON in quarantine/, not in DataLake=Y
- Non-quarantined → quarantine file NOT written
- Two records same App ID (one quarantined, one valid) → only valid to DataLake=Y
```

**Verification command:** `pytest tests/unit/test_quarantine_write.py -v`
**Invariant enforcement:** INV-09, D-08.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-8.4 — Quarantine Report Emission

**CC prompt:**
```
Implement quarantine report at end of run_pipeline():

report = {
    'run_timestamp':      datetime.now(timezone.utc).isoformat(),
    'source_zip':         str(zip_path),
    'total_records':      len(out),
    'total_quarantined':  len(quarantined),
    'quarantine_rate_pct': round(100 * len(quarantined) / max(len(out), 1), 1),
    'reason_frequency':   reason_freq_dict,
    'quarantined_app_ids': [r.app_id_canonical for r in quarantined],
}
Path(workdir / 'quarantine' / 'report.json').write_text(json.dumps(report, indent=2))

Write tests/unit/test_quarantine_report.py:
- 2 quarantined + 5 valid → report: total=7, quarantined=2, correct rates
- reason_frequency counts correct for mixed failure types
- report.json is valid JSON
```

**Verification command:** `pytest tests/unit/test_quarantine_report.py -v`
**Invariant enforcement:** None task-scoped.
**Regression classification:** REGRESSION-RELEVANT.

---

## Session 9 — Lineage + Output Write + End-to-End

**Session goal:** `run_pipeline()` against the 8-app sample produces the expected
records. Lineage complete on every record. D-13 completeness check passes.

**Integration check:**
```bash
pytest tests/integration/test_end_to_end.py -v
```

---

### TASK-9.1 — Lineage Block: Complete Record + D-10 / D-13

**CC prompt:**
```
Implement build_lineage() in full.

Required fields (all must be non-null or documented default):
  source_zip, app_id_raw, app_id_canonical, geography, client_code,
  schema_version, mapping_config_version, transform_timestamp (UTC ISO),
  source_files[] (filenames), credential_scrubbed_connectors[],
  base64_blobs_extracted[], has_connector_data (bool), validation_status,
  validation_failures[], engine_version, extra_columns_field_count (int)

TASK-SCOPED INVARIANT — D-10:
  app_id_raw = original value including _test suffix if present.
  app_id_canonical = stripped version.
  Both must be set. Neither may be null.

TASK-SCOPED INVARIANT — D-13:
  After build_lineage(), run completeness check:
  complete = all([
      rec.app_id_canonical,
      rec.lineage.get('has_connector_data'),
      rec.record.get('system',{}).get('application',{}).get('decision') is not None
          or rec.lineage.get('decision_missing'),
      rec.lineage.get('validation_status') in ('PASS', 'WARN'),
  ])
  if not complete:
      rec.lineage['record_completeness'] = 'INCOMPLETE'
      rec.validation_failures.append('D-13-incomplete-record')
      rec.quarantined = True

Write tests/unit/test_lineage.py:
- All 16 fields present after build_lineage()
- _test suffix preserved in app_id_raw, stripped in app_id_canonical
- has_connector_data=False for audit-only record
- Incomplete record → D-13 failure, quarantined
```

**Verification command:** `pytest tests/unit/test_lineage.py -v`
**Invariant enforcement:** D-10, D-13.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-9.2 — DataLake=Y Write Stub + Record Completeness Guard
*(Amendment A4 applied — workdir clearing added)*

**CC prompt:**
```
Implement DataLake=Y write path in write_record() and workdir clearing in
run_pipeline().

AMENDMENT A4 — WORKDIR CLEARING:
  At the start of run_pipeline(), immediately after root = unpack_zip(...):
      import shutil
      output_dir = Path(workdir) / 'output'
      quarantine_dir = Path(workdir) / 'quarantine'
      if output_dir.exists():
          shutil.rmtree(output_dir)
      output_dir.mkdir(parents=True)
      quarantine_dir.mkdir(parents=True, exist_ok=True)

Pre-write assertions:
  assert not rec.quarantined, f'D-08/INV-03: quarantined record reached write'
  assert rec.app_id_canonical, 'INV-04: app_id_canonical null'
  assert rec.geography in ('USA', 'CAN'), f'INV-10: invalid geography'

Write path (stub):
  out_path = Path(workdir) / 'output' / rec.geography / f'{rec.app_id_canonical}.json'
  out_path.parent.mkdir(parents=True, exist_ok=True)

TASK-SCOPED INVARIANT — INV-04:
  Before writing, check output file does not already exist (duplicate write guard):
  if out_path.exists():
      raise RuntimeError(f'INV-04 violation: duplicate write for {rec.app_id_canonical}')

TASK-SCOPED INVARIANT — D-08:
  One canonical record per application. Pre-write assert enforces this.

Write tests/unit/test_write.py:
- Valid record → JSON at correct output/{geo}/ path
- Quarantined record → assertion error raised, not written
- Duplicate App ID → RuntimeError (INV-04)
- Second run → prior output cleared (workdir clearing test)
- Output JSON is valid and contains lineage block
```

**Verification command:** `pytest tests/unit/test_write.py -v`
**Invariant enforcement:** INV-03, INV-04, INV-10, D-08.
**Regression classification:** HARNESS-CANDIDATE.

---

### TASK-9.3 — End-to-End Run: 8-App Sample

**CC prompt:**
```
Write tests/integration/test_end_to_end.py.

Run the complete pipeline against tests/fixtures/soc_sample.zip.
Note: TASK-1.5 wired dispatch_by_geo() into run_pipeline() — the dispatcher
handles USA/CAN routing internally.

Assertions:
  1. Total records returned matches expected (3 CAN + 5 USA = 8, minus known quarantines)
  2. All non-quarantined records have validation_status in ('PASS', 'WARN')
  3. All non-quarantined records have all 16 lineage fields non-null
  4. All CAN records in quarantine have multi_session_incomplete=True
     OR fff_parse_blocked=True (expected — FFF blocker active)
  5. No raw PII in any non-quarantined output record (re-run assert_no_raw_pii)
  6. No credential string in any output file:
     grep -r 'Authorization:\|password=\|Bearer ' workdir/e2e/output/ returns 0 matches
  7. Quarantine report exists and is valid JSON
  8. Score slots 4–14 null/absent in all output records
  9. No _test App ID in output/ directory
 10. app_id_raw preserved in all lineage blocks
 11. Prior run output cleared before new run (workdir clearing confirmed)
```

**Verification command:**
```bash
pytest tests/integration/test_end_to_end.py -v
grep -r "Authorization:\|password=\|Bearer " workdir/e2e/output/ \
  && echo "CREDENTIAL LEAK FOUND" || echo "No credentials in output — PASS"
```

**Invariant enforcement:** All GLOBAL + all TASK-SCOPED invariants exercised.
**Regression classification:** HARNESS-CANDIDATE — primary regression target.

---

## Invariant → Task Coverage Matrix

| Invariant | Primary task | Secondary task |
|---|---|---|
| INV-01 Credential scrub first + pattern-based | TASK-2.1, 2.2, 2.3 | TASK-9.3 |
| INV-02 PII before write (static + ExtraColumns) | TASK-7.1, 7.2, 7.3 | TASK-9.3 |
| INV-03 Validation before write | TASK-8.1 | TASK-9.2 |
| INV-04 One record per canonical App ID | TASK-3.2, 9.2 | TASK-9.3 |
| INV-07 App ID preserved without loss/truncation/overflow | TASK-1.3, 3.1 | TASK-9.3 |
| INV-09 _test never to canonical partition | TASK-3.1 | TASK-8.3 |
| INV-10 Routing explicit and deterministic | TASK-1.3, 1.4, 1.5 | TASK-9.3 |
| INV-13 Bureau evidence non-degradation | TASK-4.3, 4.4 | TASK-9.3 |
| D-01 CAN EFX timestamp > TU timestamp | TASK-3.4 | TASK-8.2 |
| D-02 All sessions share EcsDebtorNumber | TASK-3.2, 3.5 | TASK-8.2 |
| D-03 Declined app has ≥1 reasonCode | TASK-5.4 | TASK-8.2 |
| D-04 Decision from authoritative connector only | TASK-5.2 | TASK-4.1 |
| D-05 CAN bureau: both sessions + TU→EFX order | TASK-3.3, 3.4 | TASK-8.1 |
| D-06 Credentials never persisted | TASK-2.1, 2.2, 2.3 | TASK-9.3 |
| D-07 Raw PII never in DataLake=Y | TASK-7.1, 7.3 | TASK-9.3 |
| D-08 One canonical record per application | TASK-9.2 | TASK-9.3 |
| D-09 Bureau values attributable to provider | TASK-6.2 | TASK-9.3 |
| D-10 Raw App ID preserved in lineage | TASK-9.1 | TASK-3.1 |
| D-12 One authoritative source per attribute | TASK-5.5 | TASK-6.1 |
| D-13 Complete record = 5 components | TASK-9.1 | TASK-9.3 |

---

## Engineer Sign-Off

Review checklist:
- [ ] Phase 4 amendments A1–A5 correctly applied
- [ ] TASK-1.5 (dispatcher wiring) present and correct
- [ ] All 20 invariants (v1.2) have at least one primary enforcement task
- [ ] HARNESS-CANDIDATE classifications updated to reflect v1.2 invariant set
- [ ] FFF stubs (TASK-4.3, 4.4) remain stubbed — not implemented
- [ ] INV-08 slot guard retained as implementation guidance in TASK-5.3
- [ ] INV-11 protection retained as implementation guidance in TASK-3.3

**Engineer:** _____________________________ **Date:** _____________

**After sign-off:** Phase 5 closes. Produce session prompt files, then Phase 6 begins.
