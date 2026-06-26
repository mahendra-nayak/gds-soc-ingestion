"""
tests/unit/test_lineage.py — TASK-9.1
Unit tests for build_lineage() and _check_d13_completeness().

build_lineage() required fields (all 16 must be non-null or documented default):
  source_zip, app_id_raw, app_id_canonical, geography, client_code,
  schema_version, mapping_config_version, transform_timestamp (UTC ISO),
  source_files[], credential_scrubbed_connectors[], base64_blobs_extracted[],
  has_connector_data (bool), validation_status, validation_failures[],
  engine_version, extra_columns_field_count (int)

D-10: app_id_raw preserves _test suffix; app_id_canonical is stripped version.
      Both must be non-null.

D-13: completeness check after validate(); quarantines records missing any of:
  - app_id_canonical
  - has_connector_data
  - decision present OR decision_missing flag
  - validation_status in ('PASS', 'WARN')
"""
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    ClientConfig,
    SourceFile,
    _check_d13_completeness,
    build_lineage,
)

_REQUIRED_LINEAGE_FIELDS = [
    "source_zip", "app_id_raw", "app_id_canonical", "geography",
    "client_code", "schema_version", "mapping_config_version",
    "transform_timestamp", "source_files", "credential_scrubbed_connectors",
    "base64_blobs_extracted", "has_connector_data",
    "engine_version", "extra_columns_field_count",
    # validation_status + validation_failures set by validate(); present after wiring
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _cfg() -> ClientConfig:
    return ClientConfig({
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "config_version": "test-v1",
        "validation": {"hard_quarantine_rules": [], "client_params": {}},
    })


def _make_rec(app_id: str = "500249960_20250101000000",
              app_id_raw: str | None = None) -> AppRecord:
    return AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id_raw or app_id,
        geography="USA",
    )


def _sf(connector: str = "C225334") -> SourceFile:
    return SourceFile(
        path=Path("data/file.json"), folder="data",
        connector=connector, direction="RESP",
        step=1, app_id_raw="500249960", sequence_id=None,
    )


def _build(rec: AppRecord, scrubbed=None, blobs=None) -> None:
    build_lineage(rec, _cfg(), "sample.zip", scrubbed or [], blobs or [])


# ---------------------------------------------------------------------------
# TC-1: All 16 required fields present after build_lineage()
# ---------------------------------------------------------------------------
class TestAllFieldsPresent:
    def test_required_fields_all_present(self):
        rec = _make_rec()
        _build(rec)
        for field in _REQUIRED_LINEAGE_FIELDS:
            assert field in rec.lineage, f"lineage missing field: {field!r}"

    def test_source_zip_correct(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["source_zip"] == "sample.zip"

    def test_app_id_canonical_in_lineage(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["app_id_canonical"] == "500249960_20250101000000"

    def test_geography_in_lineage(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["geography"] == "USA"

    def test_client_code_in_lineage(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["client_code"] == "SOC_USA"

    def test_schema_version_in_lineage(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["schema_version"] == "1.1"

    def test_mapping_config_version_in_lineage(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["mapping_config_version"] == "test-v1"

    def test_transform_timestamp_iso_utc(self):
        rec = _make_rec()
        _build(rec)
        ts = rec.lineage["transform_timestamp"]
        dt = datetime.fromisoformat(ts)
        assert dt.tzinfo is not None

    def test_engine_version_present(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["engine_version"] is not None
        assert isinstance(rec.lineage["engine_version"], str)

    def test_extra_columns_field_count_is_int(self):
        rec = _make_rec()
        _build(rec)
        assert isinstance(rec.lineage["extra_columns_field_count"], int)

    def test_lineage_embedded_in_record(self):
        rec = _make_rec()
        _build(rec)
        assert rec.record.get("system", {}).get("lineage") is rec.lineage


# ---------------------------------------------------------------------------
# TC-2: D-10 — app_id_raw preserves _test suffix; canonical is stripped
# ---------------------------------------------------------------------------
class TestD10AppIdPreservation:
    def test_app_id_raw_preserved_with_test_suffix(self):
        rec = AppRecord(
            app_id_canonical="500249960_20250101000000",
            app_id_raw="500249960_20250101000000_test",
            geography="USA",
        )
        _build(rec)
        assert rec.lineage["app_id_raw"] == "500249960_20250101000000_test"

    def test_app_id_canonical_stripped_in_lineage(self):
        rec = AppRecord(
            app_id_canonical="500249960_20250101000000",
            app_id_raw="500249960_20250101000000_test",
            geography="USA",
        )
        _build(rec)
        assert rec.lineage["app_id_canonical"] == "500249960_20250101000000"
        assert "_test" not in rec.lineage["app_id_canonical"]

    def test_both_app_ids_non_null(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["app_id_raw"] is not None
        assert rec.lineage["app_id_canonical"] is not None


# ---------------------------------------------------------------------------
# TC-3: has_connector_data
# ---------------------------------------------------------------------------
class TestHasConnectorData:
    def test_true_when_connector_files_present(self):
        rec = _make_rec()
        rec.files.append(_sf("C225334"))
        _build(rec)
        assert rec.lineage["has_connector_data"] is True

    def test_false_for_audit_only_record(self):
        rec = _make_rec()
        # Audit files have connector=None by convention
        sf = SourceFile(
            path=Path("audit/file.json"), folder="audit",
            connector=None, direction=None,
            step=None, app_id_raw="500249960", sequence_id=None,
        )
        rec.files.append(sf)
        _build(rec)
        assert rec.lineage["has_connector_data"] is False

    def test_false_for_no_files(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["has_connector_data"] is False


# ---------------------------------------------------------------------------
# TC-4: extra_columns_field_count
# ---------------------------------------------------------------------------
class TestExtraColumnsFieldCount:
    def test_zero_when_no_extra_columns(self):
        rec = _make_rec()
        _build(rec)
        assert rec.lineage["extra_columns_field_count"] == 0

    def test_counts_leaf_values(self):
        rec = _make_rec()
        rec.extra_columns["SOC_pygdsa_attributes"] = {"a": "1", "b": "2", "c": "3"}
        _build(rec)
        assert rec.lineage["extra_columns_field_count"] == 3

    def test_counts_across_groups(self):
        rec = _make_rec()
        rec.extra_columns["group1"] = {"x": "v1"}
        rec.extra_columns["group2"] = {"y": "v2", "z": "v3"}
        _build(rec)
        assert rec.lineage["extra_columns_field_count"] == 3


# ---------------------------------------------------------------------------
# TC-5: D-13 completeness check
# ---------------------------------------------------------------------------
class TestD13Completeness:
    def _valid_rec(self) -> AppRecord:
        rec = _make_rec()
        rec.files.append(_sf())
        _build(rec)
        rec.lineage["validation_status"] = "PASS"
        rec.record.setdefault("system", {}).setdefault("application", {})["decision"] = "APPROVED"
        return rec

    def test_complete_record_not_quarantined(self):
        rec = self._valid_rec()
        _check_d13_completeness(rec)
        assert not rec.quarantined

    def test_missing_app_id_quarantines(self):
        rec = self._valid_rec()
        rec.app_id_canonical = ""
        _check_d13_completeness(rec)
        assert rec.quarantined
        assert "D-13-incomplete-record" in rec.validation_failures

    def test_no_connector_data_quarantines(self):
        rec = self._valid_rec()
        rec.lineage["has_connector_data"] = False
        _check_d13_completeness(rec)
        assert rec.quarantined

    def test_no_decision_and_no_flag_quarantines(self):
        rec = self._valid_rec()
        rec.record["system"]["application"].pop("decision", None)
        rec.lineage.pop("decision_missing", None)
        _check_d13_completeness(rec)
        assert rec.quarantined

    def test_decision_missing_flag_accepted(self):
        """D-13: documented absence is not a failure."""
        rec = self._valid_rec()
        rec.record["system"]["application"].pop("decision", None)
        rec.lineage["decision_missing"] = True
        _check_d13_completeness(rec)
        assert not rec.quarantined

    def test_fail_validation_status_quarantines(self):
        rec = self._valid_rec()
        rec.lineage["validation_status"] = "FAIL"
        _check_d13_completeness(rec)
        assert rec.quarantined

    def test_incomplete_record_sets_lineage_flag(self):
        rec = self._valid_rec()
        rec.app_id_canonical = ""
        _check_d13_completeness(rec)
        assert rec.lineage.get("record_completeness") == "INCOMPLETE"

    def test_warn_status_is_accepted(self):
        rec = self._valid_rec()
        rec.lineage["validation_status"] = "WARN"
        _check_d13_completeness(rec)
        assert not rec.quarantined
