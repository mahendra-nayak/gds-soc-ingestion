"""
tests/unit/test_can_sessions.py — TASK-3.3
Unit tests for CAN bureau session detection in _detect_can_sessions().

Implementation guidance (from removed INV-11):
  CAN session detection uses connector presence ONLY.
  sequence_id must NOT be read during CAN session detection.

D-05: CAN AppRecord with bureau_eval_indicated=True and only one session
  present must be quarantined.

TC-1: CAN with C100810 + C161796 → both sessions detected, not quarantined
TC-2: CAN with C100810 only → multi_session_incomplete=True, quarantined, REQ-VAL-003
TC-3: CAN with no bureau connectors → bureau_eval_indicated=False, not quarantined
TC-4: sequence_id sentinel — assert sequence_id not read during detection
TC-5: CAN with C161653 (alt session-2 connector) + C100810 → both sessions detected
TC-6: Lineage labels set correctly for present sessions
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import AppRecord, SourceFile
from scripts.ingest_lib import _detect_can_sessions


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_sf(connector: str | None, sequence_id: str = "1") -> SourceFile:
    return SourceFile(
        path=Path(f"fake/raw/{connector or 'none'}_file.txt"),
        folder="raw",
        connector=connector,
        direction="REQ",
        step=None,
        app_id_raw="600249966_20250101000000",
        sequence_id=sequence_id,
        geography="CAN",
    )


def _make_rec(*connectors: str | None) -> AppRecord:
    rec = AppRecord("600249966_20250101000000", "600249966_20250101000000",
                    geography="CAN")
    rec.files = [_make_sf(c) for c in connectors]
    return rec


# ---------------------------------------------------------------------------
# TC-1: Both sessions present → not quarantined
# ---------------------------------------------------------------------------
class TestBothSessionsPresent:
    def test_c100810_plus_c161796_not_quarantined(self):
        rec = _make_rec("C100810", "C161796")
        _detect_can_sessions(rec)
        assert rec.quarantined is False

    def test_no_req_val_003_when_both_present(self):
        rec = _make_rec("C100810", "C161796")
        _detect_can_sessions(rec)
        assert "REQ-VAL-003" not in rec.validation_failures

    def test_no_multi_session_incomplete_when_both_present(self):
        rec = _make_rec("C100810", "C161796")
        _detect_can_sessions(rec)
        assert rec.lineage.get("multi_session_incomplete") is None


# ---------------------------------------------------------------------------
# TC-2: Session 1 only (C100810) → quarantined, REQ-VAL-003
# ---------------------------------------------------------------------------
class TestSession1Only:
    def test_session1_only_quarantined(self):
        """D-05: one-session bureau record must be quarantined."""
        rec = _make_rec("C100810")
        _detect_can_sessions(rec)
        assert rec.quarantined is True

    def test_multi_session_incomplete_set(self):
        rec = _make_rec("C100810")
        _detect_can_sessions(rec)
        assert rec.lineage.get("multi_session_incomplete") is True

    def test_req_val_003_recorded(self):
        rec = _make_rec("C100810")
        _detect_can_sessions(rec)
        assert "REQ-VAL-003" in rec.validation_failures

    def test_session1_connector_in_lineage(self):
        rec = _make_rec("C100810")
        _detect_can_sessions(rec)
        assert "C100810" in rec.lineage.get("can_session_1_connectors", [])


# ---------------------------------------------------------------------------
# TC-3: No bureau connectors → not quarantined
# ---------------------------------------------------------------------------
class TestNoBureauConnectors:
    def test_no_bureau_connectors_not_quarantined(self):
        rec = _make_rec("C225334", "C754889")  # non-bureau connectors
        _detect_can_sessions(rec)
        assert rec.quarantined is False

    def test_no_failure_codes_without_bureau(self):
        rec = _make_rec("C225334")
        _detect_can_sessions(rec)
        assert rec.validation_failures == []

    def test_empty_session_lineage_without_bureau(self):
        rec = _make_rec("C225334")
        _detect_can_sessions(rec)
        assert rec.lineage.get("can_session_1_connectors") == []
        assert rec.lineage.get("can_session_2_connectors") == []


# ---------------------------------------------------------------------------
# TC-4: sequence_id sentinel — not read during CAN detection
# ---------------------------------------------------------------------------
class TestSequenceIdNotRead:
    def test_sentinel_sequence_id_causes_no_error(self):
        """If sequence_id were read, using a non-string sentinel would surface it."""
        rec = _make_rec("C100810", "C161796")
        # Set sequence_id to a non-comparable sentinel
        for sf in rec.files:
            sf.sequence_id = object()  # would fail numeric comparison or most string ops
        # Must not raise — sequence_id is never accessed in _detect_can_sessions
        _detect_can_sessions(rec)

    def test_result_independent_of_sequence_id_value(self):
        """Detection outcome must depend only on connector, not sequence_id."""
        rec_a = _make_rec("C100810", "C161796")
        rec_b = _make_rec("C100810", "C161796")
        for sf in rec_b.files:
            sf.sequence_id = "999999"
        _detect_can_sessions(rec_a)
        _detect_can_sessions(rec_b)
        assert rec_a.quarantined == rec_b.quarantined
        assert rec_a.validation_failures == rec_b.validation_failures


# ---------------------------------------------------------------------------
# TC-5: C161653 (alt session-2 connector) + C100810 → both sessions
# ---------------------------------------------------------------------------
class TestAlternateSession2Connector:
    def test_c161653_plus_c100810_not_quarantined(self):
        rec = _make_rec("C100810", "C161653")
        _detect_can_sessions(rec)
        assert rec.quarantined is False

    def test_session2_only_quarantined(self):
        """Session 2 alone indicates bureau eval but session 1 absent → quarantine."""
        rec = _make_rec("C161653")
        _detect_can_sessions(rec)
        assert rec.quarantined is True
        assert "REQ-VAL-003" in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-6: Lineage labels
# ---------------------------------------------------------------------------
class TestLineageLabels:
    def test_session1_label_set_when_present(self):
        rec = _make_rec("C100810", "C161796")
        _detect_can_sessions(rec)
        assert rec.lineage["can_session_1_connectors"] == ["C100810"]

    def test_session2_label_set_when_present(self):
        rec = _make_rec("C100810", "C161796")
        _detect_can_sessions(rec)
        assert rec.lineage["can_session_2_connectors"] == ["C161796"]

    def test_absent_session_has_empty_label(self):
        rec = _make_rec("C100810")
        _detect_can_sessions(rec)
        assert rec.lineage["can_session_2_connectors"] == []
