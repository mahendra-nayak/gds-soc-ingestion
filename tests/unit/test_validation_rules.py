"""
tests/unit/test_validation_rules.py — TASK-8.1
Unit tests for REQ-VAL-003, REQ-VAL-004, REQ-VAL-006.

hard_quarantine: REQ-VAL-001, 002, 003, 005, 007, 008
soft_warn:       REQ-VAL-004, 006

INV-03: validate() executes before write_record(); hard-quarantine failures block write.
D-05: REQ-VAL-003 only applies when bureau connectors are present (bureau_eval_indicated).
      FF product records are not subject to this rule.

Tests verify:
  - @rule function pass/fail behaviour in isolation (direct call)
  - validate() integration: hard failures quarantine, soft failures do not
  - D-05 conditional (REQ-VAL-003 skips non-bureau CAN records)
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    SourceFile,
    _RULES,
    validate,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(app_id: str = "500249960_20250101000000",
              geo: str = "USA") -> AppRecord:
    return AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography=geo,
    )


def _cfg_hard(*rule_ids) -> dict:
    return {
        "validation": {
            "hard_quarantine_rules": list(rule_ids),
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }
    }


def _cfg_soft(*rule_ids) -> dict:
    return {
        "validation": {
            "hard_quarantine_rules": [],
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }
    }


def _bare_cfg() -> dict:
    return {
        "validation": {
            "hard_quarantine_rules": ["REQ-VAL-003"],
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }
    }


# ---------------------------------------------------------------------------
# REQ-VAL-003 — CAN two-session rule
# ---------------------------------------------------------------------------
class TestReqVal003:
    def _rule(self):
        return _RULES["REQ-VAL-003"]

    def test_non_can_always_passes(self):
        rec = _make_rec(geo="USA")
        assert self._rule()(rec, _bare_cfg()) is True

    def test_can_no_bureau_indicated_passes(self):
        """FF product: no bureau connectors in lineage → not subject to rule."""
        rec = _make_rec(geo="CAN")
        rec.lineage["can_session_1_connectors"] = []
        rec.lineage["can_session_2_connectors"] = []
        assert self._rule()(rec, _bare_cfg()) is True

    def test_can_both_sessions_complete_passes(self):
        rec = _make_rec(geo="CAN")
        rec.lineage["can_session_1_connectors"] = ["C100810"]
        rec.lineage["can_session_2_connectors"] = ["C161796"]
        assert self._rule()(rec, _bare_cfg()) is True

    def test_can_session1_only_fails(self):
        rec = _make_rec(geo="CAN")
        rec.lineage["can_session_1_connectors"] = ["C100810"]
        rec.lineage["can_session_2_connectors"] = []
        rec.lineage["multi_session_incomplete"] = True
        assert self._rule()(rec, _bare_cfg()) is False

    def test_can_session2_only_fails(self):
        rec = _make_rec(geo="CAN")
        rec.lineage["can_session_1_connectors"] = []
        rec.lineage["can_session_2_connectors"] = ["C161796"]
        rec.lineage["multi_session_incomplete"] = True
        assert self._rule()(rec, _bare_cfg()) is False

    def test_validate_quarantines_on_incomplete_sessions(self):
        """Hard quarantine rule — validate() must set quarantined=True."""
        rec = _make_rec(geo="CAN")
        rec.lineage["can_session_1_connectors"] = ["C100810"]
        rec.lineage["can_session_2_connectors"] = []
        rec.lineage["multi_session_incomplete"] = True
        from scripts.ingest_lib import ClientConfig
        cfg = ClientConfig({"validation": {
            "hard_quarantine_rules": ["REQ-VAL-003"],
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }})
        validate(rec, cfg)
        assert rec.quarantined is True

    def test_can_no_lineage_flags_passes(self):
        """No lineage keys at all → no bureau indicated → FF product → pass."""
        rec = _make_rec(geo="CAN")
        assert self._rule()(rec, _bare_cfg()) is True


# ---------------------------------------------------------------------------
# REQ-VAL-004 — has bureau (soft-warn only, always returns True)
# ---------------------------------------------------------------------------
class TestReqVal004:
    def _rule(self):
        return _RULES["REQ-VAL-004"]

    def test_always_returns_true_with_bureau_files(self):
        rec = _make_rec()
        sf = SourceFile(
            path=Path("x.json"), folder="data",
            connector="C100810", direction="RESP",
            step=1, app_id_raw="500249960", sequence_id=None,
        )
        rec.files.append(sf)
        assert self._rule()(rec, _bare_cfg()) is True

    def test_always_returns_true_without_bureau_files(self):
        rec = _make_rec()
        assert self._rule()(rec, _bare_cfg()) is True

    def test_no_bureau_sets_lineage_flag(self):
        rec = _make_rec()
        self._rule()(rec, _bare_cfg())
        assert rec.lineage.get("has_bureau_data") is False

    def test_with_bureau_does_not_set_false_flag(self):
        rec = _make_rec()
        sf = SourceFile(
            path=Path("x.json"), folder="data",
            connector="C100810", direction="RESP",
            step=1, app_id_raw="500249960", sequence_id=None,
        )
        rec.files.append(sf)
        self._rule()(rec, _bare_cfg())
        assert rec.lineage.get("has_bureau_data") is not False

    def test_validate_never_quarantines_for_this_rule(self):
        """REQ-VAL-004 returns True always — must never quarantine."""
        rec = _make_rec()
        from scripts.ingest_lib import ClientConfig
        cfg = ClientConfig({"validation": {
            "hard_quarantine_rules": ["REQ-VAL-004"],   # even if listed as hard
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }})
        validate(rec, cfg)
        assert not rec.quarantined


# ---------------------------------------------------------------------------
# REQ-VAL-006 — decision present
# ---------------------------------------------------------------------------
class TestReqVal006:
    def _rule(self):
        return _RULES["REQ-VAL-006"]

    def test_passes_when_decision_present(self):
        rec = _make_rec()
        rec.record.setdefault("system", {}).setdefault("application", {})["decision"] = "APPROVED"
        assert self._rule()(rec, _bare_cfg()) is True

    def test_fails_when_no_decision_no_flag(self):
        rec = _make_rec()
        assert self._rule()(rec, _bare_cfg()) is False

    def test_passes_when_decision_missing_flag_set(self):
        """Documented absence (decision_missing=True) is accepted."""
        rec = _make_rec()
        rec.lineage["decision_missing"] = True
        assert self._rule()(rec, _bare_cfg()) is True

    def test_fails_when_decision_none_and_flag_false(self):
        rec = _make_rec()
        rec.lineage["decision_missing"] = False
        assert self._rule()(rec, _bare_cfg()) is False

    def test_validate_soft_warn_does_not_quarantine(self):
        """REQ-VAL-006 listed in soft_warn_rules only — no quarantine on fail."""
        rec = _make_rec()
        from scripts.ingest_lib import ClientConfig
        cfg = ClientConfig({"validation": {
            "hard_quarantine_rules": [],   # NOT in hard list
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }})
        validate(rec, cfg)
        assert not rec.quarantined

    def test_validate_appends_failure_code_on_fail(self):
        rec = _make_rec()
        from scripts.ingest_lib import ClientConfig
        cfg = ClientConfig({"validation": {
            "hard_quarantine_rules": [],
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        }})
        validate(rec, cfg)
        assert "REQ-VAL-006" in rec.validation_failures


# ---------------------------------------------------------------------------
# Regression: existing rules still pass
# ---------------------------------------------------------------------------
class TestExistingRulesUnchanged:
    def test_req_val_001_registered(self):
        assert "REQ-VAL-001" in _RULES

    def test_req_val_002_registered(self):
        assert "REQ-VAL-002" in _RULES

    def test_req_val_005_registered(self):
        assert "REQ-VAL-005" in _RULES

    def test_req_val_007_registered(self):
        assert "REQ-VAL-007" in _RULES

    def test_req_val_008_registered(self):
        assert "REQ-VAL-008" in _RULES

    def test_req_val_003_registered(self):
        assert "REQ-VAL-003" in _RULES

    def test_req_val_004_registered(self):
        assert "REQ-VAL-004" in _RULES

    def test_req_val_006_registered(self):
        assert "REQ-VAL-006" in _RULES
