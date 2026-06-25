"""
tests/unit/test_can_bureau_attribution.py — TASK-6.2
Unit tests for CAN bureau data segmentation and D-09 provider attribution.

Bureau routing:
  C100810 → rec.record['bureauData']['transunion'][field_name]
  C161796 / C161653 → rec.record['bureauData']['equifax'][field_name]
  rec.lineage['bureau_providers'] = sorted subset of ['equifax', 'transunion']

D-09: Every bureau-derived field must carry provider attribution.
      No field may exist directly at rec.record['bureauData'] root.
      rec.lineage['bureau_providers'] non-empty when bureau files present.

TC-1: C100810 fields written → under bureauData.transunion
TC-2: C161796 fields written → under bureauData.equifax
TC-3: Field at bureauData root (injected) → _assert_bureau_attribution raises ValueError
TC-4: bureau_providers lineage populated correctly
TC-5: Non-bureau records leave bureauData absent; no lineage entry
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _assert_bureau_attribution,
    _get_path,
    _set_bureau_provider_lineage,
    _set_path,
    apply_mapping,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(*files, geography: str = "CAN") -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography=geography,
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


def _bureau_row(sdd_path: str, connector: str, field_path: str) -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Bureau",
        data_type="string",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | raw | RESP",
            "path": field_path,
        }],
        transform=None,
        construction=None,
    )


def _cfg() -> dict:
    return {
        "client": {"code": "SOC_CAN", "schema_version": "1.1"},
        "connectors": [
            {"code": "C100810", "is_credential": False, "parse_strategy": "fff"},
            {"code": "C161796", "is_credential": False, "parse_strategy": "fff"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# TC-1: C100810 fields → under bureauData.transunion
# ---------------------------------------------------------------------------
class TestTransUnionRouting:
    def test_c100810_field_written_under_transunion(self):
        sf = _make_sf("C100810", "RESP", {"record": {"score": "720"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.transunion.score", "C100810", "record.score"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "bureauData.transunion.score") == "720"

    def test_c100810_field_not_at_bureau_root(self):
        sf = _make_sf("C100810", "RESP", {"record": {"score": "720"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.transunion.score", "C100810", "record.score"),
        ]
        apply_mapping(rec, mapping, _cfg())
        # score must NOT be at bureauData root
        bureau_data = rec.record.get("bureauData", {})
        assert "score" not in bureau_data

    def test_c100810_multiple_fields_all_under_transunion(self):
        sf = _make_sf(
            "C100810", "RESP", {"record": {"score": "750", "riskModel": "V9"}}
        )
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.transunion.score", "C100810", "record.score"),
            _bureau_row("bureauData.transunion.riskModel", "C100810", "record.riskModel"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "bureauData.transunion.score") == "750"
        assert _get_path(rec.record, "bureauData.transunion.riskModel") == "V9"


# ---------------------------------------------------------------------------
# TC-2: C161796 fields → under bureauData.equifax
# ---------------------------------------------------------------------------
class TestEquifaxRouting:
    def test_c161796_field_written_under_equifax(self):
        sf = _make_sf("C161796", "RESP", {"record": {"beaconScore": "680"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.equifax.beaconScore", "C161796", "record.beaconScore"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "bureauData.equifax.beaconScore") == "680"

    def test_c161796_field_not_at_bureau_root(self):
        sf = _make_sf("C161796", "RESP", {"record": {"beaconScore": "680"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.equifax.beaconScore", "C161796", "record.beaconScore"),
        ]
        apply_mapping(rec, mapping, _cfg())
        bureau_data = rec.record.get("bureauData", {})
        assert "beaconScore" not in bureau_data

    def test_both_providers_written_simultaneously(self):
        tu_sf = _make_sf("C100810", "RESP", {"record": {"score": "720"}})
        efx_sf = _make_sf("C161796", "RESP", {"record": {"beaconScore": "680"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(tu_sf, efx_sf, dec_sf)
        mapping = [
            _bureau_row("bureauData.transunion.score", "C100810", "record.score"),
            _bureau_row("bureauData.equifax.beaconScore", "C161796", "record.beaconScore"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "bureauData.transunion.score") == "720"
        assert _get_path(rec.record, "bureauData.equifax.beaconScore") == "680"


# ---------------------------------------------------------------------------
# TC-3: Field at bureauData root (injected) → D-09 guard raises
# ---------------------------------------------------------------------------
class TestD09Guard:
    def test_field_at_bureau_root_raises(self):
        rec = _make_rec()
        _set_path(rec.record, "bureauData.rawField", "some_value")
        with pytest.raises(ValueError, match="D-09"):
            _assert_bureau_attribution(rec)

    def test_field_under_unknown_provider_raises(self):
        rec = _make_rec()
        _set_path(rec.record, "bureauData.experian.score", "700")
        with pytest.raises(ValueError, match="D-09"):
            _assert_bureau_attribution(rec)

    def test_clean_record_no_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "bureauData.transunion.score", "720")
        _set_path(rec.record, "bureauData.equifax.beaconScore", "680")
        _assert_bureau_attribution(rec)   # must not raise

    def test_no_bureau_data_no_raise(self):
        rec = _make_rec()
        # bureauData absent entirely
        _assert_bureau_attribution(rec)   # must not raise

    def test_apply_mapping_raises_on_injected_root_field(self):
        """D-09 guard fires from within apply_mapping() when root field injected."""
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(dec_sf)
        _set_path(rec.record, "bureauData.orphanField", "bad_value")
        with pytest.raises(ValueError, match="D-09"):
            apply_mapping(rec, [], _cfg())


# ---------------------------------------------------------------------------
# TC-4: bureau_providers lineage populated correctly
# ---------------------------------------------------------------------------
class TestBureauProviderLineage:
    def test_transunion_only_in_lineage(self):
        tu_sf = _make_sf("C100810", "RESP", {"record": {}})
        rec = _make_rec(tu_sf)
        _set_bureau_provider_lineage(rec)
        assert rec.lineage.get("bureau_providers") == ["transunion"]

    def test_equifax_only_in_lineage(self):
        efx_sf = _make_sf("C161796", "RESP", {"record": {}})
        rec = _make_rec(efx_sf)
        _set_bureau_provider_lineage(rec)
        assert rec.lineage.get("bureau_providers") == ["equifax"]

    def test_both_providers_in_lineage(self):
        tu_sf = _make_sf("C100810", "RESP", {"record": {}})
        efx_sf = _make_sf("C161796", "RESP", {"record": {}})
        rec = _make_rec(tu_sf, efx_sf)
        _set_bureau_provider_lineage(rec)
        assert rec.lineage.get("bureau_providers") == ["equifax", "transunion"]

    def test_c161653_maps_to_equifax_provider(self):
        cred_sf = _make_sf("C161653", "RESP", None)
        rec = _make_rec(cred_sf)
        _set_bureau_provider_lineage(rec)
        assert "equifax" in rec.lineage.get("bureau_providers", [])


# ---------------------------------------------------------------------------
# TC-5: Non-bureau records — bureauData absent; no lineage entry
# ---------------------------------------------------------------------------
class TestNonBureauRecord:
    def test_usa_record_no_bureau_lineage(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf, geography="USA")
        _set_bureau_provider_lineage(rec)
        assert "bureau_providers" not in rec.lineage

    def test_usa_record_no_bureau_data(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        rec = _make_rec(sf, geography="USA")
        _set_bureau_provider_lineage(rec)
        assert "bureauData" not in rec.record
