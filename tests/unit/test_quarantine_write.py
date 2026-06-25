"""
tests/unit/test_quarantine_write.py — TASK-8.3
Unit tests for quarantine write path in write_record().

INV-09: DataLake=Y write path unreachable for rec.quarantined=True.
D-08: quarantine write uses app_id_canonical as filename key — one file per
      canonical App ID per run.

Tests:
- Quarantined → JSON written to quarantine/, not to DataLake=Y
- Non-quarantined → quarantine file NOT written
- JSON content contains required fields
- assert not rec.quarantined guard present before DataLake write path
"""
import json
import tempfile
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    ClientConfig,
    write_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(app_id: str = "500249960_20250101000000",
              quarantined: bool = False) -> AppRecord:
    rec = AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography="USA",
    )
    rec.quarantined = quarantined
    rec.lineage["validation_status"] = "FAIL" if quarantined else "PASS"
    return rec


def _cfg() -> ClientConfig:
    return ClientConfig({"validation": {
        "hard_quarantine_rules": [],
        "client_params": {},
    }})


# ---------------------------------------------------------------------------
# TC-1: Quarantined record → JSON in quarantine/
# ---------------------------------------------------------------------------
class TestQuarantineWrite:
    def test_quarantined_creates_file(self):
        rec = _make_rec(quarantined=True)
        rec.validation_failures = ["REQ-VAL-003"]
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            assert path.exists()

    def test_quarantine_json_is_valid(self):
        rec = _make_rec(quarantined=True)
        rec.validation_failures = ["REQ-VAL-001"]
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert isinstance(data, dict)

    def test_quarantine_json_has_app_id_canonical(self):
        rec = _make_rec(app_id="APP001_20250101000000", quarantined=True)
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert data["app_id_canonical"] == "APP001_20250101000000"

    def test_quarantine_json_has_app_id_raw(self):
        rec = _make_rec(quarantined=True)
        rec.app_id_raw = "500249960_20250101000000_test"
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert data["app_id_raw"] == "500249960_20250101000000_test"

    def test_quarantine_json_has_quarantine_reason(self):
        rec = _make_rec(quarantined=True)
        rec.validation_failures = ["REQ-VAL-003", "REQ-VAL-007"]
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert data["quarantine_reason"] == ["REQ-VAL-003", "REQ-VAL-007"]

    def test_quarantine_json_has_lineage(self):
        rec = _make_rec(quarantined=True)
        rec.lineage["source_zip"] = "sample.zip"
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert "lineage" in data

    def test_quarantine_json_has_geography(self):
        rec = _make_rec(quarantined=True)
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            data = json.loads(path.read_text())
            assert data["geography"] == "USA"

    def test_d08_filename_is_app_id_canonical(self):
        """D-08: filename key is app_id_canonical — one file per canonical ID."""
        rec = _make_rec(app_id="MYAPP123_20250101000000", quarantined=True)
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            expected = Path(wd) / "quarantine" / "MYAPP123_20250101000000.json"
            assert expected.exists()


# ---------------------------------------------------------------------------
# TC-2: Non-quarantined record → quarantine file NOT written
# ---------------------------------------------------------------------------
class TestNonQuarantineNoFile:
    def test_clean_record_no_quarantine_file(self):
        rec = _make_rec(quarantined=False)
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            assert not path.exists()

    def test_clean_record_quarantine_dir_may_not_exist(self):
        rec = _make_rec(quarantined=False)
        with tempfile.TemporaryDirectory() as wd:
            write_record(rec, _cfg(), wd)
            # No quarantine dir created for a clean record is also acceptable
            # (we only require the file is absent; dir creation is optional)
            path = Path(wd) / "quarantine" / f"{rec.app_id_canonical}.json"
            assert not path.exists()


# ---------------------------------------------------------------------------
# TC-3: No workdir → no file written (backward-compat signature)
# ---------------------------------------------------------------------------
class TestNoWorkdir:
    def test_quarantined_no_workdir_no_crash(self):
        rec = _make_rec(quarantined=True)
        rec.validation_failures = ["REQ-VAL-001"]
        write_record(rec, _cfg())   # no workdir — must not raise


# ---------------------------------------------------------------------------
# INV-09: assert not rec.quarantined in source
# ---------------------------------------------------------------------------
class TestInv09Guard:
    def test_assert_present_in_source(self):
        """INV-09: assert not rec.quarantined must exist before DataLake write stub."""
        import inspect
        import scripts.ingest_lib as lib
        src = inspect.getsource(lib.write_record)
        assert "assert not rec.quarantined" in src
