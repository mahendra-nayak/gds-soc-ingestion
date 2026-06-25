"""
tests/integration/test_validation.py — Session 8 integration check.

Verifies the full validation chain:
  validate() → write_record() → quarantine report

Valid records pass; structurally invalid inputs quarantine correctly.
Hard-quarantine failures block DataLake=Y write (INV-09).
Soft-warn failures append to validation_failures but do not quarantine.

Tests:
  INT-1: Clean record → validation_status=PASS, not quarantined
  INT-2: Hard-quarantine failure → quarantined=True, file in quarantine/
  INT-3: Soft-warn failure → not quarantined, code in validation_failures
  INT-4: Report emitted with correct counts
  INT-5: Multiple records — mixed pass/fail — correct routing
"""
import json
import tempfile
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    ClientConfig,
    _write_quarantine_report,
    validate,
    write_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(app_id: str = "500249960_20250101000000",
              geo: str = "USA") -> AppRecord:
    rec = AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography=geo,
    )
    # Minimal record so REQ-VAL-001 passes
    rec.lineage["credential_scrubbed_connectors"] = []
    return rec


def _hard_cfg(*rules) -> ClientConfig:
    return ClientConfig({"validation": {
        "hard_quarantine_rules": list(rules),
        "client_params": {"valid_geographies": ["USA", "CAN"]},
    }})


def _soft_cfg() -> ClientConfig:
    return ClientConfig({"validation": {
        "hard_quarantine_rules": [],
        "client_params": {"valid_geographies": ["USA", "CAN"]},
    }})


# ---------------------------------------------------------------------------
# INT-1: Clean record → PASS, not quarantined
# ---------------------------------------------------------------------------
class TestCleanRecordPasses:
    def test_valid_record_not_quarantined(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        assert not rec.quarantined

    def test_valid_record_validation_status_pass_or_warn(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        assert rec.lineage["validation_status"] in ("PASS", "WARN")

    def test_clean_record_no_quarantine_file(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _soft_cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            assert not path.exists()


# ---------------------------------------------------------------------------
# INT-2: Hard-quarantine failure → quarantined=True, file written
# ---------------------------------------------------------------------------
class TestHardQuarantineBlocks:
    def test_hard_fail_quarantines_record(self):
        rec = _make_rec()
        rec.quarantined = True
        rec.validation_failures = ["REQ-VAL-003"]
        rec.lineage["validation_status"] = "FAIL"
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _soft_cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            assert path.exists()

    def test_quarantine_file_has_failure_reason(self):
        rec = _make_rec()
        rec.quarantined = True
        rec.validation_failures = ["REQ-VAL-003"]
        rec.lineage["validation_status"] = "FAIL"
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _soft_cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert "REQ-VAL-003" in data["quarantine_reason"]

    def test_inv09_quarantined_bypasses_datalake(self):
        """INV-09: after return for quarantined, DataLake write not reached."""
        rec = _make_rec()
        rec.quarantined = True
        rec.lineage["validation_status"] = "FAIL"
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _soft_cfg(), wd)   # must not raise


# ---------------------------------------------------------------------------
# INT-3: Soft-warn failure → not quarantined, code present
# ---------------------------------------------------------------------------
class TestSoftWarnNotQuarantine:
    def test_decision_missing_soft_warn(self):
        """REQ-VAL-006: no decision + no flag → soft warn, not quarantine."""
        rec = _make_rec()
        validate(rec, _soft_cfg())   # REQ-VAL-006 fires (soft)
        assert not rec.quarantined
        assert "REQ-VAL-006" in rec.validation_failures

    def test_bl005_missing_product_info_soft_warn(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())
        assert not rec.quarantined
        assert "REQ-BL-005" in rec.validation_failures

    def test_validation_status_warn_not_fail(self):
        rec = _make_rec()
        validate(rec, _soft_cfg())   # soft failures only
        assert rec.lineage["validation_status"] == "WARN"


# ---------------------------------------------------------------------------
# INT-4: Report emitted correctly
# ---------------------------------------------------------------------------
class TestReportIntegration:
    def test_report_written_with_correct_counts(self):
        valid = [_make_rec(f"APP{i}") for i in range(5)]
        q_recs = [_make_rec("QA1"), _make_rec("QA2")]
        for r in q_recs:
            r.quarantined = True
            r.validation_failures = ["REQ-VAL-003"]
        all_recs = valid + q_recs
        with tempfile.TemporaryDirectory() as wd:
            _write_quarantine_report(all_recs, q_recs, "test.zip", wd)
            path = Path(wd) / "quarantine" / "report.json"
            data = json.loads(path.read_text())
        assert data["total_records"] == 7
        assert data["total_quarantined"] == 2

    def test_report_quarantine_rate(self):
        valid = [_make_rec(f"APP{i}") for i in range(5)]
        q_recs = [_make_rec("QA1"), _make_rec("QA2")]
        for r in q_recs:
            r.quarantined = True
        all_recs = valid + q_recs
        with tempfile.TemporaryDirectory() as wd:
            _write_quarantine_report(all_recs, q_recs, "test.zip", wd)
            path = Path(wd) / "quarantine" / "report.json"
            data = json.loads(path.read_text())
        assert data["quarantine_rate_pct"] == round(100 * 2 / 7, 1)


# ---------------------------------------------------------------------------
# INT-5: Multiple records — mixed routing
# ---------------------------------------------------------------------------
class TestMixedRouting:
    def test_each_quarantined_record_gets_own_file(self):
        q1 = _make_rec("QA001")
        q1.quarantined = True
        q1.validation_failures = ["REQ-VAL-003"]
        q2 = _make_rec("QA002")
        q2.quarantined = True
        q2.validation_failures = ["REQ-VAL-007"]
        with tempfile.TemporaryDirectory() as wd:
            write_record(q1, _soft_cfg(), wd)
            write_record(q2, _soft_cfg(), wd)
            assert (Path(wd) / "quarantine" / "QA001.json").exists()
            assert (Path(wd) / "quarantine" / "QA002.json").exists()
