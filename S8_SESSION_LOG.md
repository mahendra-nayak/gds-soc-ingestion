**Session:** S8 — Validation Rules + Quarantine Queue
**Date:** 2026-06-25
**Engineer:** Mahendra Nayak
**Branch:** session/s08_validation_quarantine

---

## Session Goal

Implement all REQ-VAL and REQ-BL rules. Valid records pass; structurally invalid
inputs quarantine correctly. Quarantine write path and quarantine report complete.

---

## Tasks Executed

### T8.1 — Hard Quarantine Rules: REQ-VAL-003, REQ-VAL-004, REQ-VAL-006

**Objective:** Add remaining validation rules using @rule() decorator.

**Work done:**
- Added `@rule("REQ-VAL-003")` `_can_two_sessions`: reads `lineage.multi_session_incomplete`
  set by `_detect_can_sessions()`. Skips non-CAN records and FF-product CAN records
  (no bureau connectors in lineage). Returns False only when bureau-indicated and
  `multi_session_incomplete=True`. D-05 compliant.
- Added `@rule("REQ-VAL-004")` `_has_bureau`: always returns True (soft-warn only).
  Side effect: sets `lineage.has_bureau_data=False` when no bureau connectors found
  in rec.files.
- Added `@rule("REQ-VAL-006")` `_decision_present`: returns False when decision absent
  AND `lineage.decision_missing` is not True. Documented absence is accepted.
- Updated `assets/client_config.SOC_USA.yaml` and `assets/client_config.SOC_CAN.yaml`:
  REQ-VAL-003 added to `hard_quarantine_rules`; REQ-VAL-004 and REQ-VAL-006 added
  to `soft_warn_rules`.
- Tests: `tests/unit/test_validation_rules.py` — 26 tests.

**Commit:** fd2f686

---

### T8.2 — Business Logic Rules: REQ-BL-001 through REQ-BL-005

**Objective:** Implement all five BL rules as @rule() decorated soft-warn functions.

**Work done:**
- `@rule("REQ-BL-001")` `_bl_reason_codes`: `return not lineage.get('reason_codes_missing', False)`.
  Reads flag set by `_check_decline_completeness()` (D-03, T5.4).
- `@rule("REQ-BL-002")` `_bl_session_order`: `return not lineage.get('session_order_anomaly', False)`.
  Reads flag set by `_check_can_session_order()` (D-01, T3.4).
- `@rule("REQ-BL-003")` `_bl_debtor_consistency`: checks for any `D-02-*` prefix in
  `rec.validation_failures`. Not a duplicate of inline code — reads from existing
  failure list, doesn't repeat the detection logic.
- `@rule("REQ-BL-004")` `_bl_pygdsa_attrs`: reads `len(rec.extra_columns.get('SOC_pygdsa_attributes', {}))`.
  If `0 < count < 100`: sets `lineage.pygdsa_parse_partial=True`, returns False.
  Returns True for 0 or ≥100. Distinct from existing inline check (reads post-mapping
  extra_columns, not raw sf.payload).
- `@rule("REQ-BL-005")` `_bl_product_info`: checks `system.application.productInformation`.
  Empty or absent → sets `lineage.product_info_incomplete=True`, returns False.
- All BL rules are soft_warn: they append to `validation_failures` but never set
  `quarantined=True` (not in `hard_quarantine_rules`).
- Tests: `tests/unit/test_bl_rules.py` — 50 tests.

**Commit:** e6c7a66

---

### T8.3 — Quarantine Queue Write

**Objective:** Implement quarantine file write path in `write_record()`.

**Work done:**
- Added optional `workdir` parameter to `write_record(rec, cfg, workdir=None)`.
- When `rec.quarantined=True` and `workdir is not None`: writes
  `{workdir}/quarantine/{app_id_canonical}.json` with quarantine record containing:
  `app_id_canonical`, `app_id_raw`, `geography`, `quarantine_reason`, `lineage`,
  `record_partial`.
- `path.parent.mkdir(exist_ok=True)` ensures `quarantine/` is created.
- Returns immediately after write (INV-09: DataLake=Y path unreachable).
- Added `assert not rec.quarantined` before DataLake write stub (INV-09 explicit guard).
- Updated `run_pipeline()` to pass `workdir` to `write_record()`.
- Tests: `tests/unit/test_quarantine_write.py` — 13 tests.

**Commit:** 70b9e9c

---

### T8.4 — Quarantine Report Emission

**Objective:** Emit `quarantine/report.json` at end of `run_pipeline()`.

**Work done:**
- Extracted `_write_quarantine_report(out, quarantined, zip_path, workdir)` function.
- `run_pipeline()` now maintains `quarantined: list[AppRecord] = []` and appends
  each `rec.quarantined=True` record after write.
- Report structure: `run_timestamp` (UTC ISO), `source_zip`, `total_records`,
  `total_quarantined`, `quarantine_rate_pct` (rounded to 1 decimal), `reason_frequency`
  (Counter over all validation_failures across quarantined records), `quarantined_app_ids`.
- `quarantine/` directory created via `path.parent.mkdir(exist_ok=True)`.
- Report written even when zero records are quarantined.
- Tests: `tests/unit/test_quarantine_report.py` — 23 tests.

**Commit:** cc654bb

---

### S8 Integration Test — `test_validation.py`

**Work done:**
- `tests/integration/test_validation.py` — 12 tests covering:
  - Clean record: validation_status=PASS/WARN, no quarantine file
  - Hard-quarantine failure: quarantined=True, file written to quarantine/
  - Soft-warn failure: not quarantined, code in validation_failures
  - REQ-VAL-006/REQ-BL-005 soft-warn integration
  - Report counts for mixed pass/fail batches
  - Multiple records each get own quarantine file (D-08)

**Commit:** 04f99b9

---

## Session Integration Check

```
pytest tests/ -q
```
**Result: 552 passed, 1 skipped**

Tests added this session: 102 new tests (26 T8.1 + 50 T8.2 + 13 T8.3 + 23 T8.4 - report overlap + 12 integration).
Prior session baseline: 450 passing (end of S7).

---

## Files Modified This Session

| File | Type | Change |
|------|------|--------|
| `scripts/ingest_lib.py` | Engine | @rule for REQ-VAL-003/004/006 + REQ-BL-001..005; write_record() quarantine path; _write_quarantine_report(); run_pipeline() quarantine tracking |
| `assets/client_config.SOC_USA.yaml` | Config | hard_quarantine_rules + soft_warn_rules updated |
| `assets/client_config.SOC_CAN.yaml` | Config | hard_quarantine_rules + soft_warn_rules updated |
| `tests/unit/test_validation_rules.py` | Test | 26 tests (T8.1) |
| `tests/unit/test_bl_rules.py` | Test | 50 tests (T8.2) |
| `tests/unit/test_quarantine_write.py` | Test | 13 tests (T8.3) |
| `tests/unit/test_quarantine_report.py` | Test | 23 tests (T8.4) |
| `tests/integration/test_validation.py` | Integration test | 12 tests (S8 check) |

---

## Invariants Enforced

| Invariant | Task | Enforcement |
|-----------|------|-------------|
| INV-03 (validate before write; hard failures block write) | T8.1 | @rule system + hard_quarantine_rules in validate() |
| D-05 (REQ-VAL-003 conditional — bureau-indicated only) | T8.1 | _can_two_sessions() checks lineage keys before evaluating |
| D-01 (BL-002 session order) | T8.2 | _bl_session_order reads lineage.session_order_anomaly |
| D-02 (BL-003 debtor consistency) | T8.2 | _bl_debtor_consistency checks D-02-* in validation_failures |
| D-03 (BL-001 reason codes) | T8.2 | _bl_reason_codes reads lineage.reason_codes_missing |
| INV-09 (DataLake=Y unreachable for quarantined) | T8.3 | assert not rec.quarantined before write stub; return after quarantine file write |
| D-08 (quarantine filename = app_id_canonical) | T8.3 | Path(workdir)/'quarantine'/f'{rec.app_id_canonical}.json' |
