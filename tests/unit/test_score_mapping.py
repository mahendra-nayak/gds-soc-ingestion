"""
tests/unit/test_score_mapping.py — TASK-5.3
Unit tests for score slot mapping and slot bounding (SOC_USA).

Score mapping:
  score1: C225334-RESP record.FICO    (string_to_numeric transform)
  score2: C225334-RESP record.SOC_RiskScore (null in sample — map if present)
  score3: C225334-RESP record.CustomScore   (null in sample — map if present)

Slot bounding (implementation guidance — INV-08 removed, guard retained):
  Slots 4-14 must remain unpopulated for SOC. ValueError raised on violation.

TC-1: FICO='680' → system.application.scores.score1=680 (int after numeric transform)
TC-2: score4 populated by injection → ValueError raised by _check_score_slot_bounds
TC-3: score2, score3 null → graceful null (not written to record)
TC-4: string_to_numeric transform strips non-numerics correctly
TC-5: slot bound check passes when only slots 1-3 are populated
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _check_score_slot_bounds,
    _get_path,
    _set_path,
    apply_mapping,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(*files) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    rec.files = list(files)
    return rec


def _make_sf(connector: str, direction: str, payload, folder: str = "raw") -> SourceFile:
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


def _score_row(sdd_path: str, connector: str, field_path: str,
               transform: str = "string_to_numeric") -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Score",
        data_type="numeric",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | raw | RESP",
            "path": field_path,
        }],
        transform=transform,
        construction=None,
    )


def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# TC-1: FICO='680' → score1=680 (int after numeric transform)
# ---------------------------------------------------------------------------
class TestFicoScore1:
    def test_fico_string_mapped_to_int(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score1") == 680

    def test_fico_result_is_int_not_string(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "720"}})
        rec = _make_rec(sf)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.scores.score1")
        assert isinstance(result, int)

    def test_fico_with_leading_zeros_stripped(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "0680"}})
        rec = _make_rec(sf)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score1") == 680


# ---------------------------------------------------------------------------
# TC-2: score4 injected → ValueError raised by _check_score_slot_bounds
# ---------------------------------------------------------------------------
class TestSlotBounding:
    def test_score4_populated_raises_value_error(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.scores.score4", 999)
        with pytest.raises(ValueError, match="slot 4"):
            _check_score_slot_bounds(rec)

    def test_score14_populated_raises_value_error(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.scores.score14", 500)
        with pytest.raises(ValueError, match="slot 14"):
            _check_score_slot_bounds(rec)

    def test_score3_populated_does_not_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.scores.score3", 720)
        _check_score_slot_bounds(rec)   # must not raise

    def test_slot_bounding_via_apply_mapping_raises(self):
        """apply_mapping calls _check_score_slot_bounds — injection triggers it."""
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf)
        _set_path(rec.record, "system.application.scores.score5", 123)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        with pytest.raises(ValueError, match="slot 5"):
            apply_mapping(rec, mapping, _cfg())


# ---------------------------------------------------------------------------
# TC-3: score2, score3 null → not written to record (graceful)
# ---------------------------------------------------------------------------
class TestNullScores:
    def test_null_score2_not_written(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf)
        mapping = [
            _score_row("system.application.scores.score1", "C225334", "record.FICO"),
            _score_row("system.application.scores.score2", "C225334", "record.SOC_RiskScore"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score2") is None

    def test_null_score3_not_written(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf)
        mapping = [
            _score_row("system.application.scores.score3", "C225334", "record.CustomScore"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score3") is None


# ---------------------------------------------------------------------------
# TC-4: string_to_numeric strips non-numerics
# ---------------------------------------------------------------------------
class TestNumericTransform:
    def test_score_with_space_stripped(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": " 700 "}})
        rec = _make_rec(sf)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score1") == 700

    def test_score_float_preserved(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "720.5"}})
        rec = _make_rec(sf)
        mapping = [_score_row("system.application.scores.score1", "C225334", "record.FICO")]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.scores.score1")
        assert result == 720.5


# ---------------------------------------------------------------------------
# TC-5: slots 1-3 populated — slot bound check passes
# ---------------------------------------------------------------------------
class TestSlotBoundPassesWith1To3:
    def test_scores_1_2_3_do_not_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.scores.score1", 680)
        _set_path(rec.record, "system.application.scores.score2", 720)
        _set_path(rec.record, "system.application.scores.score3", 750)
        _check_score_slot_bounds(rec)   # must not raise
