"""
tests/unit/test_app_id.py — TASK-3.1
Unit tests for _canonicalise_app_id() and the INV-09 / INV-07 / D-10 invariants
enforced in group_by_app().

Invariants verified:
  INV-09: records with app_id_raw ending in '_test' are quarantined; never
    written to DataLake=Y.
  INV-07 / D-10: app_id_canonical and app_id_raw are VARCHAR strings at every
    stage; no numeric coercion.

TC-1: Standard app_id_raw → app_id_canonical unchanged, no test flag
TC-2: _test suffix → canonical stripped by 5 chars, test flag set, rec quarantined
TC-3: app_id_raw preserved in lineage after canonicalisation
TC-4: app_id_canonical is a string (INV-07 / D-10)
TC-5: Both app_id_raw and app_id_canonical present in rec.lineage
TC-6: Non-_test record not quarantined
TC-7: test_quarantine lineage flag set on _test record
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import AppRecord, ClientConfig, SourceFile, group_by_app


# ---------------------------------------------------------------------------
# Config stubs
# ---------------------------------------------------------------------------
def _cfg_with_suffix_rules() -> ClientConfig:
    return ClientConfig({
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "application_id": {
            "source": "filename_tokens",
            "filename": {"pattern": ".*", "canonical_app_id_groups": ["debtor", "dt"]},
            "suffix_rules": [{"suffix": "_test", "action": "strip", "flag_lineage": True}],
        },
        "sessions": {"model": "single"},
    })


def _cfg_no_suffix_rules() -> ClientConfig:
    return ClientConfig({
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "application_id": {
            "source": "filename_tokens",
            "filename": {"pattern": ".*", "canonical_app_id_groups": ["debtor", "dt"]},
            "suffix_rules": [],
        },
        "sessions": {"model": "single"},
    })


def _make_sf(app_id_raw: str, connector: str = "C225334") -> SourceFile:
    return SourceFile(
        path=Path(f"fake/raw/{app_id_raw}_file.txt"),
        folder="raw",
        connector=connector,
        direction="REQ",
        step=None,
        app_id_raw=app_id_raw,
        sequence_id="1",
        geography="USA",
    )


# ---------------------------------------------------------------------------
# TC-1: Standard app_id_raw → canonical unchanged, no test flag
# ---------------------------------------------------------------------------
class TestStandardAppId:
    def test_canonical_equals_raw_for_standard(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert rec.app_id_canonical == "500249966_20250101000000"

    def test_no_test_flag_for_standard(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert rec.lineage.get("app_id_raw_had_test_suffix") is None

    def test_app_id_raw_preserved_as_str(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert isinstance(rec.app_id_raw, str)
        assert rec.app_id_raw == "500249966_20250101000000"


# ---------------------------------------------------------------------------
# TC-2: _test suffix → canonical stripped, test flag set, quarantined
# ---------------------------------------------------------------------------
class TestTestSuffixAppId:
    def _rec(self) -> AppRecord:
        sf = _make_sf("500249966_20250101000000_test")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        return apps["500249966_20250101000000"]

    def test_canonical_strips_test_suffix(self):
        rec = self._rec()
        assert rec.app_id_canonical == "500249966_20250101000000"

    def test_test_flag_set_in_lineage(self):
        rec = self._rec()
        assert rec.lineage.get("app_id_raw_had_test_suffix") is True

    def test_record_quarantined(self):
        """INV-09: _test records must be quarantined."""
        rec = self._rec()
        assert rec.quarantined is True

    def test_test_quarantine_lineage_flag(self):
        """INV-09: test_quarantine flag must be set in lineage."""
        rec = self._rec()
        assert rec.lineage.get("test_quarantine") is True

    def test_canonical_is_string(self):
        """INV-07 / D-10: canonical must be VARCHAR string — no numeric cast."""
        rec = self._rec()
        assert isinstance(rec.app_id_canonical, str)


# ---------------------------------------------------------------------------
# TC-3 / TC-5: app_id_raw and app_id_canonical preserved in lineage
# ---------------------------------------------------------------------------
class TestLineagePreservation:
    def test_app_id_raw_in_lineage(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert "app_id_raw" in rec.lineage
        assert rec.lineage["app_id_raw"] == "500249966_20250101000000"

    def test_app_id_canonical_in_lineage(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert "app_id_canonical" in rec.lineage
        assert rec.lineage["app_id_canonical"] == "500249966_20250101000000"

    def test_original_raw_preserved_in_lineage_for_test_record(self):
        """app_id_raw in lineage must be the original value (with _test suffix)."""
        sf = _make_sf("500249966_20250101000000_test")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert rec.lineage["app_id_raw"] == "500249966_20250101000000_test"

    def test_lineage_canonical_is_stripped_for_test_record(self):
        sf = _make_sf("500249966_20250101000000_test")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert rec.lineage["app_id_canonical"] == "500249966_20250101000000"


# ---------------------------------------------------------------------------
# TC-4 / TC-6: Standard record not quarantined; types are strings
# ---------------------------------------------------------------------------
class TestNonTestRecordNotQuarantined:
    def test_standard_record_not_quarantined(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg_with_suffix_rules())
        rec = apps["500249966_20250101000000"]
        assert rec.quarantined is False

    def test_app_id_canonical_is_str_type(self):
        """INV-07 / D-10: canonical must be str — confirm type, not just value."""
        sf = _make_sf("123456789_20250101120000")
        apps = group_by_app([sf], _cfg_no_suffix_rules())
        rec = apps["123456789_20250101120000"]
        assert type(rec.app_id_canonical) is str

    def test_no_numeric_cast(self):
        """INV-07: verify canonical is not int/float at any point."""
        sf = _make_sf("999999999_20991231235959")
        apps = group_by_app([sf], _cfg_no_suffix_rules())
        key = "999999999_20991231235959"
        rec = apps[key]
        assert isinstance(rec.app_id_canonical, str)
        assert isinstance(rec.app_id_raw, str)
