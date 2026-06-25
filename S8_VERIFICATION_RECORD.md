**Session:** S8 — Validation Rules + Quarantine Queue
**Date:** 2026-06-25
**Engineer:** Mahendra Nayak

---

## Task 8.1 — Hard Quarantine Rules: REQ-VAL-003, REQ-VAL-004, REQ-VAL-006

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 8 TASK-8.1

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| V003-1a | Non-CAN geography → REQ-VAL-003 always passes | True | PASS |
| V003-1b | CAN, no bureau lineage keys → FF product → passes | True | PASS |
| V003-1c | CAN, both sessions complete → passes | True | PASS |
| V003-1d | CAN, session1 only + multi_session_incomplete=True → fails | False | PASS |
| V003-1e | CAN, session2 only + multi_session_incomplete=True → fails | False | PASS |
| V003-1f | validate() sets quarantined=True for incomplete CAN | quarantined | PASS |
| V003-1g | CAN, no lineage flags → FF product → passes | True | PASS |
| V004-1a | Bureau files present → returns True | True | PASS |
| V004-1b | No bureau files → returns True (soft-warn) | True | PASS |
| V004-1c | No bureau files → lineage.has_bureau_data=False | flag set | PASS |
| V004-1d | Bureau files → flag not set to False | no false flag | PASS |
| V004-1e | validate() never quarantines for REQ-VAL-004 | not quarantined | PASS |
| V006-1a | Decision present → passes | True | PASS |
| V006-1b | No decision, no flag → fails | False | PASS |
| V006-1c | decision_missing=True → documented absence accepted | True | PASS |
| V006-1d | decision_missing=False → fails | False | PASS |
| V006-1e | validate() soft-warn: no quarantine | not quarantined | PASS |
| V006-1f | validate() appends REQ-VAL-006 to failures | code present | PASS |
| REG-001 | REQ-VAL-001..008 all registered in _RULES | present | PASS |
| pytest | `pytest tests/unit/test_validation_rules.py -v` | 26 passed | PASS — 26 passed |

**Verdict:** CLEAN
**Status:** PASS

---

## Task 8.2 — Business Logic Rules: REQ-BL-001 through REQ-BL-005

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 8 TASK-8.2

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| BL001-1a | reason_codes_missing absent → passes | True | PASS |
| BL001-1b | reason_codes_missing=False → passes | True | PASS |
| BL001-1c | reason_codes_missing=True → fails | False | PASS |
| BL001-1d | validate() appends REQ-BL-001 | code present | PASS |
| BL001-1e | validate() does not quarantine | not quarantined | PASS |
| BL002-1a | session_order_anomaly absent → passes | True | PASS |
| BL002-1b | session_order_anomaly=False → passes | True | PASS |
| BL002-1c | session_order_anomaly=True → fails | False | PASS |
| BL002-1d | validate() appends REQ-BL-002 | code present | PASS |
| BL002-1e | validate() does not quarantine | not quarantined | PASS |
| BL003-1a | No D-02 failures → passes | True | PASS |
| BL003-1b | Unrelated failures only → passes | True | PASS |
| BL003-1c | D-02-payload-debtor-mismatch present → fails | False | PASS |
| BL003-1d | Any D-02-* variant → fails | False | PASS |
| BL003-1e | validate() appends REQ-BL-003 | code present | PASS |
| BL003-1f | validate() does not quarantine | not quarantined | PASS |
| BL004-1a | No SOC_pygdsa_attributes group → passes | True | PASS |
| BL004-1b | Exactly 100 attrs → passes | True | PASS |
| BL004-1c | More than 100 attrs → passes | True | PASS |
| BL004-1d | 50 attrs → fails | False | PASS |
| BL004-1e | 1 attr → fails | False | PASS |
| BL004-1f | 0 attrs → passes (0 < 0 is False) | True | PASS |
| BL004-1g | Fail sets lineage.pygdsa_parse_partial=True | flag set | PASS |
| BL004-1h | validate() appends REQ-BL-004 | code present | PASS |
| BL004-1i | validate() does not quarantine | not quarantined | PASS |
| BL005-1a | productInformation present → passes | True | PASS |
| BL005-1b | productInformation absent → fails | False | PASS |
| BL005-1c | productInformation empty list → fails | False | PASS |
| BL005-1d | Fail sets lineage.product_info_incomplete=True | flag set | PASS |
| BL005-1e | validate() appends REQ-BL-005 | code present | PASS |
| BL005-1f | validate() does not quarantine | not quarantined | PASS |
| REG-BL | All 5 BL rules registered | all present | PASS |
| pytest | `pytest tests/unit/test_bl_rules.py -v` | 50 passed | PASS — 50 passed |

**Verdict:** CLEAN
**Status:** PASS

---

## Task 8.3 — Quarantine Queue Write

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 8 TASK-8.3

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| QW-1a | Quarantined → JSON file in quarantine/ | file exists | PASS |
| QW-1b | Quarantine JSON is valid JSON | parseable | PASS |
| QW-1c | JSON has app_id_canonical | correct value | PASS |
| QW-1d | JSON has app_id_raw | correct value | PASS |
| QW-1e | JSON has quarantine_reason with failure codes | codes match | PASS |
| QW-1f | JSON has lineage | present | PASS |
| QW-1g | JSON has geography | 'USA' | PASS |
| QW-1h (D-08) | Filename = app_id_canonical.json | correct path | PASS |
| QW-2a | Non-quarantined → quarantine file NOT written | file absent | PASS |
| QW-2b | Non-quarantined → quarantine dir may not exist | file absent | PASS |
| QW-3a | No workdir → no crash (backward compat) | no exception | PASS |
| INV-09 | assert not rec.quarantined present in source | code present | PASS |
| pytest | `pytest tests/unit/test_quarantine_write.py -v` | 13 passed | PASS — 13 passed |

**Verdict:** CLEAN
**Status:** PASS

---

## Task 8.4 — Quarantine Report Emission

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 8 TASK-8.4

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| QR-1a | 5 valid + 2 quarantined → total_records=7 | 7 | PASS |
| QR-1b | 5 valid + 2 quarantined → total_quarantined=2 | 2 | PASS |
| QR-1c | 2/7 = 28.6% quarantine rate | 28.6 | PASS |
| QR-1d | 0 quarantined → rate=0.0 | 0.0 | PASS |
| QR-1e | All quarantined → rate=100.0 | 100.0 | PASS |
| QR-2a | Single reason counted correctly | count=1 | PASS |
| QR-2b | Repeated reason counted across records | count=2 | PASS |
| QR-2c | Mixed reasons counted independently | each correct | PASS |
| QR-2d | No quarantined → empty reason_frequency | {} | PASS |
| QR-3a | report.json exists after call | file exists | PASS |
| QR-3b | report.json is valid JSON | parseable | PASS |
| QR-3c | source_zip recorded in report | correct value | PASS |
| QR-3d | run_timestamp is ISO with timezone | UTC timezone | PASS |
| QR-4a | quarantined_app_ids lists quarantined IDs | IDs present | PASS |
| QR-4b | Non-quarantined not in IDs list | absent | PASS |
| QR-4c | 0 quarantined → empty IDs list | [] | PASS |
| pytest | `pytest tests/unit/test_quarantine_report.py -v` | 23 passed | PASS — 23 passed |

**Verdict:** CLEAN
**Status:** PASS

---

## Session 8 Integration Check

### `pytest tests/integration/test_validation.py -v`

| Case | Scenario | Expected | Result |
|------|----------|----------|--------|
| INT-1a | Clean record → not quarantined | False | PASS |
| INT-1b | Clean record → validation_status PASS or WARN | PASS/WARN | PASS |
| INT-1c | Clean record → no quarantine file | file absent | PASS |
| INT-2a | Hard-quarantine: quarantined=True, file written | both true | PASS |
| INT-2b | Quarantine file has failure reason | code present | PASS |
| INT-2c | INV-09: write_record does not raise for quarantined | no error | PASS |
| INT-3a | REQ-VAL-006 soft-warn: not quarantined | False | PASS |
| INT-3b | REQ-BL-005 soft-warn: not quarantined | False | PASS |
| INT-3c | Soft-warn only → validation_status=WARN | WARN | PASS |
| INT-4a | Report: 5+2 records → total=7, quarantined=2 | correct | PASS |
| INT-4b | Report: quarantine rate correct | 28.6% | PASS |
| INT-5a | Two quarantined records → two separate files | both exist | PASS |
| pytest | `pytest tests/integration/test_validation.py -v` | 12 passed | PASS — 12 passed |

**Verdict:** CLEAN
**Status:** PASS

---

## Session 8 — Verification Summary

| Task | Verdict | Status |
|------|---------|--------|
| 8.1 Hard Quarantine Rules | CLEAN | PASS |
| 8.2 Business Logic Rules | CLEAN | PASS |
| 8.3 Quarantine Queue Write | CLEAN | PASS |
| 8.4 Quarantine Report Emission | CLEAN | PASS |
| S8 Integration: test_validation.py | CLEAN | PASS |

**Session integration check result:**
```bash
pytest tests/ -q
```
Result: **552 passed, 1 skipped**
(102 new tests added this session; 450 prior tests all remain green)
