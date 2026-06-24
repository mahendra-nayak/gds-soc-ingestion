**Session:** S3 — App ID Parsing + Session Assembly
**Date:** 2026-06-24
**Engineer:** Mahendra Nayak

---

## Task 3.1 — Canonical App ID + _test Isolation

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3 TASK-3.1

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | Standard app_id_raw | canonical unchanged; no test flag; not quarantined | N/A | PASS |
| TC-2 | `_test` suffix | canonical stripped by 5 chars; test flag set; rec.quarantined=True | N/A | PASS |
| TC-3 | app_id_raw preserved in lineage | `rec.lineage['app_id_raw']` == original (with `_test`) | N/A | PASS |
| TC-4 | app_id_canonical type | `type(rec.app_id_canonical) is str` — INV-07/D-10 | N/A | PASS |
| TC-5 | Both IDs in lineage | `rec.lineage['app_id_raw']` and `rec.lineage['app_id_canonical']` both set | N/A | PASS |
| TC-6 | Non-test not quarantined | `rec.quarantined is False` | N/A | PASS |
| TC-7 | `test_quarantine` lineage flag | `rec.lineage['test_quarantine'] is True` | N/A | PASS |
| pytest | `pytest tests/unit/test_app_id.py -v` | 15 passed | N/A | PASS — 15 passed in 0.67s |

**Verdict:** CLEAN
**Status:** PASS

---

## Task 3.2 — group_by_app() with Composite Dedup Key

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3 TASK-3.2

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | 5 USA + 3 CAN distinct App IDs | 8 AppRecord objects returned | N/A | PASS |
| TC-2 | USA retry — same (connector, direction, sequence_id) | 1 SourceFile retained (latest filename) | N/A | PASS |
| TC-3 | Cross-debtor mismatch | AppRecord quarantined; D-02-cross-session-identity-mismatch | N/A | PASS |
| TC-4 | Empty file list | `{}` returned — no error | N/A | PASS |
| TC-5 | Files with app_id_raw=None | Skipped — no AppRecord created | N/A | PASS |
| TC-6 | Different sequence_id | Both files retained (not duplicates) | N/A | PASS |
| pytest | `pytest tests/unit/test_grouping.py -v` | 14 passed | N/A | PASS — 14 passed in 0.20s |

**Verdict:** FINDINGS

**Finding dispositions:**

| Finding # | Disposition | Rationale / Test case added | Test result |
|-----------|-------------|------------------------------|-------------|
| F-3.2-01 | ACCEPT | EXECUTION_PLAN dedup key includes `transaction_id` which is not a SourceFile field. Dedup key uses `(connector, direction, sequence_id)` instead. `transaction_id` is a payload field not available pre-parse. Noted as Out of Scope Observation for future session. | N/A |

**Status:** PASS (F-3.2-01 ACCEPTED — scope limitation documented)

---

## Task 3.3 — CAN Session Detection (Connector Presence)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3 TASK-3.3

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | CAN with C100810 + C161796 | Both sessions detected; not quarantined | N/A | PASS |
| TC-2 | CAN with C100810 only | `multi_session_incomplete=True`; quarantined; REQ-VAL-003 | N/A | PASS |
| TC-3 | CAN with no bureau connectors | `bureau_eval_indicated=False`; not quarantined | N/A | PASS |
| TC-4 | sequence_id sentinel | sequence_id never read — no error with non-string sentinel | N/A | PASS |
| TC-5 | C161653 + C100810 | Both sessions detected; not quarantined | N/A | PASS |
| TC-6 | Lineage labels | `can_session_1_connectors` and `can_session_2_connectors` set correctly | N/A | PASS |
| pytest | `pytest tests/unit/test_can_sessions.py -v` | 17 passed | N/A | PASS — 17 passed in 0.26s |

**Verdict:** CLEAN
**Status:** PASS

---

## Task 3.4 — CAN Session Ordering Check (D-01)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3 TASK-3.4

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | EFX later than TU | No anomaly flag; no REQ-BL-002 | N/A | PASS |
| TC-2 | EFX earlier than TU | `session_order_anomaly=True`; REQ-BL-002 | N/A | PASS |
| TC-3 | Equal timestamps | `session_order_anomaly=True` (strictly greater required) | N/A | PASS |
| TC-4 | No datetimes set | Check skipped gracefully; no error | N/A | PASS |
| TC-5 | Ordering anomaly does not quarantine | `rec.quarantined is False` — soft-warn only | N/A | PASS |
| pytest | `pytest tests/unit/test_can_ordering.py -v` | 12 passed | N/A | PASS — 12 passed in 0.26s |

**Verdict:** CLEAN

**Scope observation:** `sf.datetime` not populated by `_classify_file` (filename `ts` regex group not captured). Tests set `sf.datetime` directly. Out-of-scope observation noted in session log.

**Status:** PASS

---

## Task 3.5 — EcsDebtorNumber Cross-Session Consistency (D-02 payload)

### Test Cases Applied
Source: EXECUTION_PLAN.md Session 3 TASK-3.5

| Case | Scenario | Expected | UI Tests | Result |
|------|----------|----------|----------|--------|
| TC-1 | All sessions same debtor | No quarantine | N/A | PASS |
| TC-2 | Two sessions different debtors | Quarantined; D-02-payload-debtor-mismatch | N/A | PASS |
| TC-3 | No debtor in payloads | No quarantine; no error | N/A | PASS |
| TC-4 | C225334-REQ extraction | `payload['record']['EcsDebtorNumber']` extracted | N/A | PASS |
| TC-5 | C103403-RESP extraction | `payload['attributes']['EcsDebtorNumber']` extracted | N/A | PASS |
| TC-6 | data/ folder extraction | `payload['data']['EcsDebtorNumber']` extracted (non-C225334/C103403 connector) | N/A | PASS |
| pytest | `pytest tests/unit/test_debtor_consistency.py -v` | 17 passed | N/A | PASS — 17 passed in 0.28s |

**Verdict:** CLEAN
**Status:** PASS

---

## Session 3 — Verification Summary

| Task | Verdict | Status |
|------|---------|--------|
| 3.1 Canonical App ID + _test Isolation | CLEAN | PASS |
| 3.2 group_by_app() Composite Dedup + D-02 | FINDINGS (F-3.2-01 ACCEPTED) | PASS |
| 3.3 CAN Session Detection | CLEAN | PASS |
| 3.4 CAN Session Ordering Check | CLEAN | PASS |
| 3.5 EcsDebtorNumber Cross-Session Consistency | CLEAN | PASS |

**Session integration check result:**
```bash
pytest tests/ -v
```
Result: 184 passed, 1 skipped in 12.30s
(1 skip = TC-5 in T1.5, deferred pending client_config population)
