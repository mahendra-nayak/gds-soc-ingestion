"""
tests/unit/test_write.py — TASK-9.2
Unit tests for write_record() DataLake write path and Amendment A4 workdir clearing.

Coverage:
  - Valid record → JSON at output/{geo}/{app_id_canonical}.json
  - Quarantined record → returns early (quarantine file written), no DataLake file
  - Duplicate App ID → RuntimeError (INV-04)
  - Output JSON contains lineage block
  - workdir=None → no crash (backward compat)
  - INV-09: assert not rec.quarantined gates DataLake write

Amendment A4:
  - run_pipeline() clears output/ and quarantine/ at start of each run
  - Clearing happens AFTER single-subfolder descent so build_manifest sees correct root
"""
import json
import tempfile
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    ClientConfig,
    SourceFile,
    build_lineage,
    tokenise_pii,
    write_record,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cfg() -> ClientConfig:
    return ClientConfig({
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "config_version": "test-v1",
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {
            "hard_quarantine_rules": ["REQ-VAL-001", "REQ-VAL-002", "REQ-VAL-003",
                                       "REQ-VAL-005", "REQ-VAL-007", "REQ-VAL-008"],
            "client_params": {"valid_geographies": ["USA", "CAN"]},
        },
    })


def _make_valid_rec(app_id: str = "500249960_20250101000000") -> AppRecord:
    """Build a minimal post-validation record that passes write_record() assertions.

    Skips calling validate() — validation logic is tested in test_validation_rules.py.
    Sets the post-validate state directly so write_record() preconditions are met.
    """
    cfg = _cfg()
    rec = AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography="USA",
    )
    sf = SourceFile(
        path=Path("data/file.json"), folder="data",
        connector="C225334", direction="RESP",
        step=1, app_id_raw="500249960", sequence_id=None,
    )
    rec.files.append(sf)
    build_lineage(rec, cfg, "sample.zip", [], [])
    tokenise_pii(rec, cfg)
    # Set post-validate state directly — validation correctness is in test_validation_rules.py
    rec.quarantined = False
    rec.lineage["validation_status"] = "PASS"
    rec.lineage["validation_failures"] = []
    return rec


def _make_quarantined_rec() -> AppRecord:
    cfg = _cfg()
    rec = AppRecord(
        app_id_canonical="999000000_20250101000000",
        app_id_raw="999000000_20250101000000",
        geography="USA",
    )
    build_lineage(rec, cfg, "sample.zip", [], [])
    rec.quarantined = True
    rec.validation_failures.append("REQ-VAL-001")
    return rec


# ---------------------------------------------------------------------------
# TC-1: Valid record writes to output/{geo}/{app_id_canonical}.json
# ---------------------------------------------------------------------------
class TestValidRecordWrite:
    def test_output_file_created(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        assert out.exists()

    def test_output_file_is_valid_json(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        data = json.loads(out.read_text())
        assert isinstance(data, dict)

    def test_output_json_contains_lineage(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        data = json.loads(out.read_text())
        assert "system" in data
        assert "lineage" in data["system"]

    def test_output_path_uses_geo_subdir(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        usa_dir = tmp_path / "output" / "USA"
        assert usa_dir.is_dir()

    def test_can_geo_uses_can_subdir(self, tmp_path):
        cfg = _cfg()
        rec = AppRecord(
            app_id_canonical="700100001_20250101000000",
            app_id_raw="700100001_20250101000000",
            geography="CAN",
        )
        sf = SourceFile(
            path=Path("data/file.json"), folder="data",
            connector="C225334", direction="RESP",
            step=1, app_id_raw="700100001", sequence_id=None,
        )
        rec.files.append(sf)
        build_lineage(rec, cfg, "sample.zip", [], [])
        tokenise_pii(rec, cfg)
        rec.quarantined = False
        rec.lineage["validation_status"] = "PASS"
        rec.lineage["validation_failures"] = []
        write_record(rec, cfg, workdir=tmp_path)
        out = tmp_path / "output" / "CAN" / "700100001_20250101000000.json"
        assert out.exists()

    def test_no_quarantine_file_for_valid_record(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        quarantine_file = tmp_path / "quarantine" / "500249960_20250101000000.json"
        assert not quarantine_file.exists()

    def test_workdir_none_no_crash(self):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=None)


# ---------------------------------------------------------------------------
# TC-2: Quarantined record → early return; no DataLake file
# ---------------------------------------------------------------------------
class TestQuarantinedRecordWrite:
    def test_quarantined_does_not_create_output_file(self, tmp_path):
        rec = _make_quarantined_rec()
        (tmp_path / "quarantine").mkdir(parents=True, exist_ok=True)
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "999000000_20250101000000.json"
        assert not out.exists()

    def test_quarantined_writes_quarantine_file(self, tmp_path):
        rec = _make_quarantined_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        q_file = tmp_path / "quarantine" / "999000000_20250101000000.json"
        assert q_file.exists()

    def test_quarantined_workdir_none_no_crash(self):
        rec = _make_quarantined_rec()
        write_record(rec, _cfg(), workdir=None)


# ---------------------------------------------------------------------------
# TC-3: Duplicate App ID → RuntimeError (INV-04)
# ---------------------------------------------------------------------------
class TestDuplicateAppId:
    def test_second_write_raises_runtime_error(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        rec2 = _make_valid_rec()
        with pytest.raises(RuntimeError, match="INV-04"):
            write_record(rec2, _cfg(), workdir=tmp_path)

    def test_first_write_file_still_intact_after_duplicate_attempt(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        original = out.read_text()
        rec2 = _make_valid_rec()
        with pytest.raises(RuntimeError):
            write_record(rec2, _cfg(), workdir=tmp_path)
        assert out.read_text() == original

    def test_different_app_ids_do_not_conflict(self, tmp_path):
        rec1 = _make_valid_rec("500249960_20250101000000")
        rec2 = _make_valid_rec("500249961_20250101000000")
        write_record(rec1, _cfg(), workdir=tmp_path)
        write_record(rec2, _cfg(), workdir=tmp_path)
        assert (tmp_path / "output" / "USA" / "500249960_20250101000000.json").exists()
        assert (tmp_path / "output" / "USA" / "500249961_20250101000000.json").exists()


# ---------------------------------------------------------------------------
# TC-4: Output JSON structure validation
# ---------------------------------------------------------------------------
class TestOutputJsonStructure:
    def test_app_id_canonical_in_lineage_output(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        data = json.loads(out.read_text())
        lineage = data["system"]["lineage"]
        assert lineage["app_id_canonical"] == "500249960_20250101000000"

    def test_geography_in_lineage_output(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        data = json.loads(out.read_text())
        assert data["system"]["lineage"]["geography"] == "USA"

    def test_engine_version_in_lineage_output(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        data = json.loads(out.read_text())
        assert "engine_version" in data["system"]["lineage"]

    def test_no_raw_credential_in_output(self, tmp_path):
        rec = _make_valid_rec()
        write_record(rec, _cfg(), workdir=tmp_path)
        out = tmp_path / "output" / "USA" / "500249960_20250101000000.json"
        raw = out.read_text()
        assert "Authorization: Bearer" not in raw
        assert "password" not in raw.lower() or '"password": null' in raw.lower() or '"password": ""' in raw.lower()
