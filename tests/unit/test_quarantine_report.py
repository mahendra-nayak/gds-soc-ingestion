"""
tests/unit/test_quarantine_report.py — TASK-8.4
Unit tests for quarantine report emission at end of run_pipeline() via
_write_quarantine_report().

Tests:
- 2 quarantined + 5 valid → report: total=7, quarantined=2, correct rate
- reason_frequency counts correct for mixed failure types
- report.json is valid JSON
- quarantined_app_ids correct
- run_timestamp is ISO-format string
- report written to quarantine/report.json
"""
import json
import tempfile
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    _write_quarantine_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(app_id: str, failures: list[str] | None = None) -> AppRecord:
    rec = AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography="USA",
    )
    if failures:
        rec.quarantined = True
        rec.validation_failures = failures
    return rec


def _run_report(out_recs, q_recs, tmp_dir):
    _write_quarantine_report(out_recs, q_recs, "sample.zip", tmp_dir)
    path = Path(tmp_dir) / "quarantine" / "report.json"
    return json.loads(path.read_text())


# ---------------------------------------------------------------------------
# TC-1: Counts — 2 quarantined + 5 valid → total=7, quarantined=2
# ---------------------------------------------------------------------------
class TestReportCounts:
    def test_total_records_correct(self):
        all_recs = [_make_rec(f"APP{i}") for i in range(5)]
        q = [_make_rec("QA1", ["REQ-VAL-003"]), _make_rec("QA2", ["REQ-VAL-007"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, q, wd)
        assert data["total_records"] == 7

    def test_quarantined_count_correct(self):
        all_recs = [_make_rec(f"APP{i}") for i in range(5)]
        q = [_make_rec("QA1", ["REQ-VAL-003"]), _make_rec("QA2", ["REQ-VAL-007"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, q, wd)
        assert data["total_quarantined"] == 2

    def test_quarantine_rate_correct(self):
        """2/7 = 28.6%"""
        all_recs = [_make_rec(f"APP{i}") for i in range(5)]
        q = [_make_rec("QA1", ["REQ-VAL-003"]), _make_rec("QA2", ["REQ-VAL-007"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, q, wd)
        assert data["quarantine_rate_pct"] == round(100 * 2 / 7, 1)

    def test_zero_quarantined_rate_is_zero(self):
        all_recs = [_make_rec(f"APP{i}") for i in range(5)]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, [], wd)
        assert data["quarantine_rate_pct"] == 0.0
        assert data["total_quarantined"] == 0

    def test_all_quarantined_rate_is_100(self):
        q = [_make_rec("QA1", ["REQ-VAL-003"]), _make_rec("QA2", ["REQ-VAL-007"])]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(q, q, wd)
        assert data["quarantine_rate_pct"] == 100.0


# ---------------------------------------------------------------------------
# TC-2: reason_frequency correct for mixed failure types
# ---------------------------------------------------------------------------
class TestReasonFrequency:
    def test_single_reason_counted(self):
        q = [_make_rec("QA1", ["REQ-VAL-003"])]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(q, q, wd)
        assert data["reason_frequency"]["REQ-VAL-003"] == 1

    def test_repeated_reason_counted(self):
        q = [
            _make_rec("QA1", ["REQ-VAL-003"]),
            _make_rec("QA2", ["REQ-VAL-003"]),
        ]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(q, q, wd)
        assert data["reason_frequency"]["REQ-VAL-003"] == 2

    def test_mixed_reasons_counted_independently(self):
        q = [
            _make_rec("QA1", ["REQ-VAL-003", "REQ-VAL-007"]),
            _make_rec("QA2", ["REQ-VAL-007"]),
        ]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(q, q, wd)
        assert data["reason_frequency"]["REQ-VAL-003"] == 1
        assert data["reason_frequency"]["REQ-VAL-007"] == 2

    def test_empty_quarantined_empty_frequency(self):
        all_recs = [_make_rec("APP1")]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, [], wd)
        assert data["reason_frequency"] == {}


# ---------------------------------------------------------------------------
# TC-3: report.json is valid JSON
# ---------------------------------------------------------------------------
class TestReportJson:
    def test_report_file_exists(self):
        all_recs = [_make_rec("APP1")]
        q = [_make_rec("QA1", ["REQ-VAL-001"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            _write_quarantine_report(all_recs, q, "test.zip", wd)
            path = Path(wd) / "quarantine" / "report.json"
            assert path.exists()

    def test_report_is_valid_json(self):
        all_recs = [_make_rec("APP1")]
        q = [_make_rec("QA1", ["REQ-VAL-001"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, q, wd)
        assert isinstance(data, dict)

    def test_source_zip_recorded(self):
        all_recs = [_make_rec("APP1")]
        with tempfile.TemporaryDirectory() as wd:
            _write_quarantine_report(all_recs, [], "sample.zip", wd)
            path = Path(wd) / "quarantine" / "report.json"
            data = json.loads(path.read_text())
        assert data["source_zip"] == "sample.zip"

    def test_run_timestamp_is_iso_format(self):
        all_recs = [_make_rec("APP1")]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, [], wd)
        ts = data["run_timestamp"]
        # Must be parseable as an ISO datetime
        from datetime import datetime
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None   # UTC timezone set


# ---------------------------------------------------------------------------
# TC-4: quarantined_app_ids correct
# ---------------------------------------------------------------------------
class TestQuarantinedAppIds:
    def test_quarantined_ids_listed(self):
        q = [_make_rec("QA1", ["REQ-VAL-003"]), _make_rec("QA2", ["REQ-VAL-007"])]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(q, q, wd)
        assert "QA1" in data["quarantined_app_ids"]
        assert "QA2" in data["quarantined_app_ids"]

    def test_non_quarantined_not_in_list(self):
        all_recs = [_make_rec("CLEAN")]
        q = [_make_rec("QA1", ["REQ-VAL-001"])]
        all_recs.extend(q)
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, q, wd)
        assert "CLEAN" not in data["quarantined_app_ids"]

    def test_empty_quarantine_empty_ids_list(self):
        all_recs = [_make_rec("APP1")]
        with tempfile.TemporaryDirectory() as wd:
            data = _run_report(all_recs, [], wd)
        assert data["quarantined_app_ids"] == []
