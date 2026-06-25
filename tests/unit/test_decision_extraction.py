"""
tests/unit/test_decision_extraction.py — TASK-5.2
Unit tests for decision extraction from C238743-RESP in apply_mapping().

Invariants verified:
  D-04: Only C238743-RESP (non-audit) may set rec.record['decision'].
        Audit-folder files are silently skipped even if they carry a decision value.
        The only connector that may write system.application.decision is C238743.

TC-1: C238743-RESP decision='APP' → system.application.decision='APP'
TC-2: C238743-RESP absent → decision_missing=True, REQ-VAL-006 in failures
TC-3: Audit folder C238743-RESP with decision → ignored (D-04 guard fires)
TC-4: APR extracted alongside decision from Decision.interestrate
TC-5: C238743-RESP with payload but no decision field → decision_missing=True
"""
import pytest

from scripts.ingest_lib import AppRecord, SourceFile, _extract_decision, _get_path
from pathlib import Path


def _make_rec(*files) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    rec.files = list(files)
    return rec


def _make_sf(connector: str, direction: str, payload, folder: str = "data") -> SourceFile:
    return SourceFile(
        path=Path(f"fake/{folder}/{connector}_{direction}.json"),
        folder=folder,
        connector=connector,
        direction=direction,
        step=None,
        app_id_raw="500249960_20250101000000",
        sequence_id="1",
        payload=payload,
    )


# ---------------------------------------------------------------------------
# TC-1: C238743-RESP decision present → written to system.application.decision
# ---------------------------------------------------------------------------
class TestDecisionExtracted:
    def test_decision_app_written_to_record(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP", "interestrate": "5.5"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.decision") == "APP"

    def test_decision_declined_written(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.decision") == "DECLINED"

    def test_decision_present_no_decision_missing_flag(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert not rec.lineage.get("decision_missing")
        assert "REQ-VAL-006" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-2: C238743-RESP absent → decision_missing=True, REQ-VAL-006
# ---------------------------------------------------------------------------
class TestDecisionAbsent:
    def test_no_c238743_sets_decision_missing(self):
        sf = _make_sf("C225334", "REQ", {"record": {"FICO": "720"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert rec.lineage.get("decision_missing") is True

    def test_no_c238743_appends_req_val_006(self):
        rec = _make_rec()   # no files at all
        _extract_decision(rec)
        assert "REQ-VAL-006" in rec.validation_failures

    def test_c238743_req_not_resp_treated_as_absent(self):
        sf = _make_sf("C238743", "REQ", {"Decision": {"decision": "APP"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert rec.lineage.get("decision_missing") is True
        assert "REQ-VAL-006" in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-3: Audit folder C238743-RESP → ignored (D-04 guard)
# ---------------------------------------------------------------------------
class TestAuditFolderIgnored:
    def test_audit_folder_not_used_for_decision(self):
        audit_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP"}}, folder="audit")
        rec = _make_rec(audit_sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.decision") is None

    def test_audit_folder_triggers_decision_missing(self):
        audit_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP"}}, folder="audit")
        rec = _make_rec(audit_sf)
        _extract_decision(rec)
        assert rec.lineage.get("decision_missing") is True

    def test_data_folder_takes_precedence_over_audit(self):
        """Data-folder C238743-RESP wins; audit-folder one is ignored (D-04)."""
        data_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP"}}, folder="data")
        audit_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}}, folder="audit")
        rec = _make_rec(audit_sf, data_sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.decision") == "APP"


# ---------------------------------------------------------------------------
# TC-4: APR extracted from Decision.interestrate
# ---------------------------------------------------------------------------
class TestAprExtraction:
    def test_apr_written_when_present(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP", "interestrate": "5.5"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.apr") == "5.5"

    def test_no_apr_key_when_interestrate_absent(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APP"}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert _get_path(rec.record, "system.application.apr") is None


# ---------------------------------------------------------------------------
# TC-5: C238743-RESP present but Decision.decision field missing
# ---------------------------------------------------------------------------
class TestDecisionFieldMissing:
    def test_empty_decision_object_sets_missing(self):
        sf = _make_sf("C238743", "RESP", {"Decision": {}})
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert rec.lineage.get("decision_missing") is True
        assert "REQ-VAL-006" in rec.validation_failures

    def test_none_payload_sets_missing(self):
        sf = _make_sf("C238743", "RESP", None)
        rec = _make_rec(sf)
        _extract_decision(rec)
        assert rec.lineage.get("decision_missing") is True
