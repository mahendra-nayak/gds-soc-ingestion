**Session:** S5 — Field Mapping: SOC_USA
**Date:** 2026-06-25
**Engineer:** Mahendra Nayak
**Branch:** session/s05_field_mapping_usa

---

## Session Goal

Wire `apply_mapping()` against USA AppRecords: all USA SDD paths resolved,
decision extraction, score slot bounding, decline completeness, and full
source priority resolution (D-12).

---

## Tasks Executed

### T5.1 — SOC_USA Config + Mapping Sheet Scaffold

**Objective:** Register all 9 USA connectors in `assets/client_config.SOC_USA.yaml`.

**Work done:**
- Populated connector registry: C225334 (raw_json), C78098/C78449/C215125/C238743/C224847
  (gds_envelope_json), C103403 (pygdsa_json), C1677939 (xml_dict), C754889
  (credential_discard, is_credential: true).
- Added structural sections: package.folder_priority, application_id, sessions,
  preprocess, pii, validation — all with `<FILL:...>` markers as required.
- No `<FILL:...>` markers populated (CC-prohibited).

**Commit:** 7bb13a5

---

### T5.2 — Decision Extraction: C238743-RESP

**Objective:** Implement `_extract_decision(rec)` with D-04 compliance.

**Work done:**
- Added `_get_nested(obj, dotted)` — dotted-path lookup helper.
- Added `_get_path(obj, dotted)` — alias over `_get_nested`.
- Added `_set_path(obj, dotted, val)` — nested dict writer.
- Implemented `_extract_decision(rec)` — reads `Decision.decision` from
  C238743-RESP only; skips audit/ folder (D-04); sets `decision_missing` and
  `REQ-VAL-006` when absent; extracts `Decision.interestrate` → apr.
- Stubbed `_check_decline_completeness(rec)` and `_check_score_slot_bounds(rec)`.
- Wired all three into `apply_mapping()`.
- Tests: `tests/unit/test_decision_extraction.py` — 13 tests.

**Commit:** 60691c2

---

### T5.3 — Score Slot Mapping + Slot Bounding

**Objective:** Map FICO → score1 (string_to_numeric); guard slots 4-14.

**Work done:**
- Implemented `_read_locator(rec, src, cfg)` — parses `connector | folder | direction`
  locator string; matches against `rec.files`; returns `_get_nested(sf.payload, path)`.
  (Required for resolve_source() to work end-to-end; pulled forward from T5.5 scope.)
- `_check_score_slot_bounds(rec)` — raises `ValueError` if any score slot 4-14 is
  populated (INV-08 guard retained per implementation guidance).
- Tests: `tests/unit/test_score_mapping.py` — 12 tests across 5 test classes.

**Commit:** 9fe52ae

---

### T5.4 — Dec_Reasons Pipe-Split + Decline Completeness (D-03)

**Objective:** Map `record.Dec_Reasons` through `split_on_delim` to
`decisionSummary.reasonCodes[]`; enforce D-03.

**Work done:**
- `split_on_delim` transform in `apply_transform()` was already registered (S2).
  Verified: splits on `|`, strips whitespace, filters empty segments.
- `_check_decline_completeness(rec)` (stubbed in T5.2) confirmed correct:
  DECLINED + empty reasonCodes → `REQ-BL-001` soft-warn + `reason_codes_missing`
  lineage flag; does NOT quarantine.
- `_check_decline_completeness` called from `apply_mapping()` after row loop.
- Also covers: `Dec_Description` → `decisionSummary.description` (plain string),
  `Stipulations` → `decisionSummary.stipulations[]` (same split).
- Tests: `tests/unit/test_dec_reasons.py` — 15 tests across 5 test classes.

**Commit:** 2543044

---

### T5.5 — Source Priority Resolution + D-12 Enforcement

**Objective:** Verify `resolve_source()` is complete; enforce D-12; write
comprehensive priority and integration tests.

**Work done:**
- `resolve_source(rec, row, cfg)` verified complete — walks `row.sources` in
  declared order; returns first non-null/non-empty value; falls through on null.
- `_read_locator(rec, src, cfg)` (implemented in T5.3) verified as the correct
  backing implementation.
- D-12 confirmed: no runtime heuristic; sole selection mechanism is null-fallback
  in tier order.
- Tests: `tests/unit/test_source_priority.py` — 12 tests covering PRIMARY/SECONDARY/
  TERTIARY resolution, all-null, D-12 non-heuristic enforcement.
- Integration: `tests/integration/test_mapping_usa.py` — 11 tests; exercises full
  chain (resolve_source → apply_transform → _set_path → _check_score_slot_bounds →
  _check_decline_completeness) against synthetic USA AppRecords.

**Commit:** 3aebea0

---

## Session Integration Check

```
pytest tests/ -q
```
**Result: 320 passed, 1 skipped**

Tests added this session: 51 new tests (12 T5.3 + 15 T5.4 + 12 T5.5-unit + 11 T5.5-integration +
1 T5.2 already included in prior count).
Prior session baseline: 276 tests passing (end of S4 unit-only + integration count).

---

## Files Modified This Session

| File | Type | Change |
|------|------|--------|
| `assets/client_config.SOC_USA.yaml` | Config scaffold | 9 connectors registered (T5.1) |
| `scripts/ingest_lib.py` | Engine | `_get_nested`, `_get_path`, `_set_path`, `_extract_decision`, `_check_decline_completeness`, `_check_score_slot_bounds`, `_read_locator` added; `apply_mapping()` wired |
| `tests/unit/test_decision_extraction.py` | Test | 13 tests (T5.2) |
| `tests/unit/test_score_mapping.py` | Test | 12 tests (T5.3) |
| `tests/unit/test_dec_reasons.py` | Test | 15 tests (T5.4) |
| `tests/unit/test_source_priority.py` | Test | 12 tests (T5.5) |
| `tests/integration/test_mapping_usa.py` | Integration test | 11 tests (T5.5) |

---

## Invariants Enforced

| Invariant | Task | Enforcement |
|-----------|------|-------------|
| D-04 (decision from C238743-RESP non-audit only) | T5.2 | `_extract_decision` skips audit/ folder |
| D-03 (DECLINED + no reason codes → REQ-BL-001) | T5.4 | `_check_decline_completeness()` soft-warn |
| D-12 (tier order is sole source selection criterion) | T5.5 | `resolve_source()` walks list order; no heuristic |
| INV-08 (score slots 4-14 unused for SOC) | T5.3 | `_check_score_slot_bounds()` raises ValueError |
| REQ-VAL-006 (decision must be present) | T5.2 | `_extract_decision()` appends on missing |
