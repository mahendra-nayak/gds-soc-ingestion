**Session:** S6 — Field Mapping: SOC_CAN
**Date:** 2026-06-25
**Engineer:** Mahendra Nayak
**Branch:** session/s06_field_mapping_can

---

## Session Goal

Wire `apply_mapping()` against CAN AppRecords: bureau data segmented by provider
(D-09), FFF connectors quarantined, ExtraColumns groups registered and routed,
double-encoded JSON transforms implemented.

---

## Tasks Executed

### T6.1 — SOC_CAN Config + Mapping Sheet Scaffold

**Objective:** Validate `client_config.SOC_CAN.yaml`; add CAN-specific connectors.

**Work done:**
- Added C100810 (is_credential: false, parse_strategy: fff) — TransUnion CAN.
- Added C161796 (is_credential: false, parse_strategy: fff) — Equifax CAN.
- Kept C161653 (is_credential: true, parse_strategy: credential_discard).
- Added all shared connectors (C225334, C78098, C78449, C103403, C215125, C238743,
  C224847) matching USA parse_strategy values.
- Added structural sections (package, application_id, sessions, preprocess, pii,
  validation) with `<FILL:...>` markers — no markers populated (CC-prohibited).
- sessions.model set to `can_multi` (CAN multi-session model, per S3.T3).
- Ran inline Python sync check: `Shared connector sync: PASS`.

**Commit:** e7d0645

---

### T6.2 — CAN Bureau Attribution: D-09

**Objective:** Segment bureau data by provider; enforce D-09 attribution invariant.

**Work done:**
- Added `_BUREAU_PROVIDER_MAP` constant: `{C100810: 'transunion', C161796: 'equifax',
  C161653: 'equifax'}`.
- Implemented `_set_bureau_provider_lineage(rec)` — populates
  `rec.lineage['bureau_providers']` from bureau connectors present in `rec.files`.
- Implemented `_assert_bureau_attribution(rec)` — raises `ValueError("D-09: ...")`
  if any key at `rec.record['bureauData']` root is not `'transunion'` or `'equifax'`.
- Wired both into `apply_mapping()` after the row loop.
- Routing itself done at MappingRow level: sdd_path `bureauData.transunion.*` or
  `bureauData.equifax.*` (existing `_set_path` handles nested write).
- Tests: `tests/unit/test_can_bureau_attribution.py` — 17 tests across 5 classes.

**Commit:** 4c00867

---

### T6.3 — Double-Encoded JSON Fields

**Objective:** Implement `json_double_parse` and `ast_literal_eval` transforms.

**Work done:**
- Added `import ast` to engine imports.
- Added `json_double_parse` branch to `apply_transform()`: `json.loads(value)`.
- Added `ast_literal_eval` branch to `apply_transform()`: `ast.literal_eval(value)`.
  Only `ast.literal_eval()` used — never bare `eval()` (IC-4 / CC must-not).
- Grep check confirms zero bare `eval()` calls in engine.
- Tests: `tests/unit/test_double_parse.py` — 16 tests; includes static `eval()`
  assertion and security test that function-call expression raises ValueError.

**Commit:** 8e93205

---

### T6.4 — ExtraColumns Group Registration

**Objective:** Register four ExtraColumns groups in both configs; route `extra_columns.*`
sdd_paths to `rec.extra_columns`, not `rec.record`.

**Work done:**
- Added `extra_columns_groups` section to `assets/client_config.SOC_USA.yaml` and
  `assets/client_config.SOC_CAN.yaml` — four groups registered in each:
  SOC_pygdsa_attributes (C103403), SOC_derived_application (C225334),
  SOC_decision_variable (C225334), SOC_decision_req (C238743).
- Modified `apply_mapping()` row loop: if `row.sdd_path.startswith("extra_columns.")`,
  writes to `rec.extra_columns` via `_set_path(rec.extra_columns, rest, value)`;
  otherwise writes to `rec.record` as before. D-13 enforced.
- Added `_step_nested(cur, part)` helper — extends `_get_nested()` to handle numeric
  dotted-path parts as list indices (e.g., `DerivedApplicationRecord.0.Payload`).
  Refactored `_get_nested()` to use `_step_nested()` (CQ-001 compliant).
- Tests: `tests/unit/test_extra_columns.py` — 12 tests.

**Finding:** F-6.4-01 — `_get_nested` couldn't handle numeric list indices required by
the `DerivedApplicationRecord.0.Payload` path (spec uses `[0]` access). Fixed by
extracting `_step_nested()` with list-index support. See verification record.

**Commit:** 6529e3e

---

### S6 Integration Test — `test_mapping_can.py`

**Work done:**
- `tests/integration/test_mapping_can.py` — 11 tests covering:
  - Bureau attribution (TransUnion + Equifax under correct paths)
  - bureau_providers lineage populated
  - D-09 guard fires from within `apply_mapping()`
  - FFF quarantine (C100810, C161796) via `_handle_fff_quarantine()`
  - Decision extraction on CAN records (D-04 audit guard)
  - ExtraColumns double-parse routing to `rec.extra_columns`
  - pygdsa attrs to `rec.extra_columns`

**Commit:** 7019ce5

---

## Session Integration Check

```
pytest tests/ -q
```
**Result: 376 passed, 1 skipped**

Tests added this session: 56 new tests (17 T6.2 + 16 T6.3 + 12 T6.4 + 11 integration).
Prior session baseline: 320 passing (end of S5).

---

## Files Modified This Session

| File | Type | Change |
|------|------|--------|
| `assets/client_config.SOC_CAN.yaml` | Config scaffold | Full scaffold + C100810/C161796 + extra_columns_groups |
| `assets/client_config.SOC_USA.yaml` | Config | extra_columns_groups section added |
| `scripts/ingest_lib.py` | Engine | `_BUREAU_PROVIDER_MAP`, `_set_bureau_provider_lineage`, `_assert_bureau_attribution`, `_step_nested`, `_get_nested` refactor, `json_double_parse`/`ast_literal_eval` transforms, `apply_mapping` extra_columns routing, `import ast` |
| `tests/unit/test_can_bureau_attribution.py` | Test | 17 tests (T6.2) |
| `tests/unit/test_double_parse.py` | Test | 16 tests (T6.3) |
| `tests/unit/test_extra_columns.py` | Test | 12 tests (T6.4) |
| `tests/integration/test_mapping_can.py` | Integration test | 11 tests (S6 check) |

---

## Invariants Enforced

| Invariant | Task | Enforcement |
|-----------|------|-------------|
| D-09 (bureau fields must carry provider attribution) | T6.2 | `_assert_bureau_attribution()` raises on root-level bureauData fields |
| D-13 (extra_columns separate from core schema) | T6.4 | `apply_mapping()` routes `extra_columns.*` paths to `rec.extra_columns` |
| IC-4 / CC must-not (no eval()) | T6.3 | `ast.literal_eval()` only; static grep assertion in test |
| INV-13 (FFF = hard quarantine) | Integration | `_handle_fff_quarantine()` tested for C100810 + C161796 |
| D-04 (decision from C238743-RESP non-audit) | Integration | Verified in CAN integration tests |
