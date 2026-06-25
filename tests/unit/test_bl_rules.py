"""
tests/unit/test_bl_rules.py — TASK-8.2
Unit tests for REQ-BL-001 through REQ-BL-005.

All BL rules are soft_warn — they append to validation_failures but never quarantine.

REQ-BL-001: reads lineage.reason_codes_missing (set by D-03 _check_decline_completeness)
REQ-BL-002: reads lineage.session_order_anomaly (set by D-01 _check_can_session_order)
REQ-BL-003: checks for D-02-* codes in validation_failures
REQ-BL-004: attr_count = len(extra_columns.get('SOC_pygdsa_attributes',{})); <100 → warn
REQ-BL-005: productInformation absent → lineage flag + warn

Tests cover pass and fail for each rule, plus validate() integration (soft-warn only).
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    ClientConfig,
    _RULES,
    validate,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(geo: str = "USA") -> AppRecord:
    return AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography=geo,
    )


def _soft_cfg() -> ClientConfig:
    """Config with empty hard_quarantine_rules — all BL rules are soft."""
    return ClientConfig({"validation": {
        "hard_quarantine_rules": [],
        "client_params": {"valid_geographies": ["USA", "CAN"]},
    }})


# ---------------------------------------------------------------------------
# REQ-BL-001 — reason codes missing (D-03)
# ---------------------------------------------------------------------------
class TestReqBl001:
    def _rule(self):
        return _RULES["REQ-BL-001"]

    def test_passes_when_flag_absent(self):
        rec = _make_rec()
        assert self._rule()(rec, _soft_cfg()) is True

    def test_passes_when_flag_false(self):
        rec = _make_rec()
        rec.lineage["reason_codes_missing"] = False
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fails_when_flag_true(self):
        rec = _make_rec()
        rec.lineage["reason_codes_missing"] = True
        assert self._rule()(rec, _soft_cfg()) is False

    def test_validate_appends_bl001_on_fail(self):
        rec = _make_rec()
        rec.lineage["reason_codes_missing"] = True
        validate(rec, _soft_cfg())
        assert "REQ-BL-001" in rec.validation_failures

    def test_validate_does_not_quarantine(self):
        rec = _make_rec()
        rec.lineage["reason_codes_missing"] = True
        validate(rec, _soft_cfg())
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# REQ-BL-002 — session order anomaly (D-01)
# ---------------------------------------------------------------------------
class TestReqBl002:
    def _rule(self):
        return _RULES["REQ-BL-002"]

    def test_passes_when_flag_absent(self):
        rec = _make_rec()
        assert self._rule()(rec, _soft_cfg()) is True

    def test_passes_when_flag_false(self):
        rec = _make_rec()
        rec.lineage["session_order_anomaly"] = False
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fails_when_anomaly_detected(self):
        rec = _make_rec()
        rec.lineage["session_order_anomaly"] = True
        assert self._rule()(rec, _soft_cfg()) is False

    def test_validate_appends_bl002_on_fail(self):
        rec = _make_rec()
        rec.lineage["session_order_anomaly"] = True
        validate(rec, _soft_cfg())
        assert "REQ-BL-002" in rec.validation_failures

    def test_validate_does_not_quarantine(self):
        rec = _make_rec()
        rec.lineage["session_order_anomaly"] = True
        validate(rec, _soft_cfg())
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# REQ-BL-003 — debtor consistency (D-02)
# ---------------------------------------------------------------------------
class TestReqBl003:
    def _rule(self):
        return _RULES["REQ-BL-003"]

    def test_passes_when_no_d02_failures(self):
        rec = _make_rec()
        assert self._rule()(rec, _soft_cfg()) is True

    def test_passes_when_unrelated_failures_only(self):
        rec = _make_rec()
        rec.validation_failures.append("REQ-VAL-005")
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fails_when_d02_present(self):
        rec = _make_rec()
        rec.validation_failures.append("D-02-payload-debtor-mismatch")
        assert self._rule()(rec, _soft_cfg()) is False

    def test_fails_when_any_d02_variant_present(self):
        rec = _make_rec()
        rec.validation_failures.append("D-02-cross-debtor-mismatch")
        assert self._rule()(rec, _soft_cfg()) is False

    def test_validate_appends_bl003_when_d02_present(self):
        rec = _make_rec()
        rec.validation_failures.append("D-02-payload-debtor-mismatch")
        validate(rec, _soft_cfg())
        assert "REQ-BL-003" in rec.validation_failures

    def test_validate_does_not_quarantine(self):
        rec = _make_rec()
        rec.validation_failures.append("D-02-payload-debtor-mismatch")
        validate(rec, _soft_cfg())
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# REQ-BL-004 — pygdsa attr count < 100
# ---------------------------------------------------------------------------
class TestReqBl004:
    def _rule(self):
        return _RULES["REQ-BL-004"]

    def test_passes_when_no_group(self):
        rec = _make_rec()
        assert self._rule()(rec, _soft_cfg()) is True

    def test_passes_when_exactly_100_attrs(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(100)}
        assert self._rule()(rec, _soft_cfg()) is True

    def test_passes_when_more_than_100_attrs(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(150)}
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fails_when_fewer_than_100_attrs(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(50)}
        assert self._rule()(rec, _soft_cfg()) is False

    def test_fails_when_exactly_1_attr(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {"k": "v"}
        assert self._rule()(rec, _soft_cfg()) is False

    def test_passes_when_zero_attrs(self):
        """Empty group (0 attrs) → 0 < 0 is False → pass (not partial)."""
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {}
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fail_sets_lineage_flag(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(30)}
        self._rule()(rec, _soft_cfg())
        assert rec.lineage.get("pygdsa_parse_partial") is True

    def test_validate_appends_bl004_on_fail(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(30)}
        validate(rec, _soft_cfg())
        assert "REQ-BL-004" in rec.validation_failures

    def test_validate_does_not_quarantine(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {str(i): "v" for i in range(30)}
        validate(rec, _soft_cfg())
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# REQ-BL-005 — productInformation
# ---------------------------------------------------------------------------
class TestReqBl005:
    def _rule(self):
        return _RULES["REQ-BL-005"]

    def test_passes_when_product_info_present(self):
        rec = _make_rec()
        (rec.record.setdefault("system", {})
         .setdefault("application", {})["productInformation"]) = [{"type": "PERSONAL_LOAN"}]
        assert self._rule()(rec, _soft_cfg()) is True

    def test_fails_when_product_info_missing(self):
        rec = _make_rec()
        assert self._rule()(rec, _soft_cfg()) is False

    def test_fails_when_product_info_empty_list(self):
        rec = _make_rec()
        (rec.record.setdefault("system", {})
         .setdefault("application", {})["productInformation"]) = []
        assert self._rule()(rec, _soft_cfg()) is False

    def test_fail_sets_lineage_flag(self):
        rec = _make_rec()
        self._rule()(rec, _soft_cfg())
        assert rec.lineage.get("product_info_incomplete") is True

    def test_validate_appends_bl005_on_fail(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        assert "REQ-BL-005" in rec.validation_failures

    def test_validate_does_not_quarantine(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# Regression: all BL rules registered
# ---------------------------------------------------------------------------
class TestBlRulesRegistered:
    def test_req_bl_001_registered(self):
        assert "REQ-BL-001" in _RULES

    def test_req_bl_002_registered(self):
        assert "REQ-BL-002" in _RULES

    def test_req_bl_003_registered(self):
        assert "REQ-BL-003" in _RULES

    def test_req_bl_004_registered(self):
        assert "REQ-BL-004" in _RULES

    def test_req_bl_005_registered(self):
        assert "REQ-BL-005" in _RULES
