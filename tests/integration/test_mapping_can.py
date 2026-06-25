"""
tests/integration/test_mapping_can.py — Session 6 integration check.

Verifies apply_mapping() against synthetic CAN AppRecords:
  - Bureau data segmented under bureauData.transunion / bureauData.equifax (D-09)
  - FFF connectors (C100810, C161796) produce quarantined records (INV-13)
  - ExtraColumns written to rec.extra_columns, not rec.record
  - Decision extraction from C238743-RESP (D-04)
  - bureau_providers lineage populated
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _assert_bureau_attribution,
    _get_path,
    _handle_fff_quarantine,
    apply_mapping,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sf(connector: str, direction: str, payload, folder: str = "raw") -> SourceFile:
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


def _rec(*files, geography: str = "CAN") -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography=geography,
    )
    rec.files = list(files)
    return rec


def _row(sdd_path: str, connector: str, field_path: str,
         transform: str = None, folder: str = "raw",
         direction: str = "RESP") -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Attribute",
        data_type="string",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | {folder} | {direction}",
            "path": field_path,
        }],
        transform=transform,
        construction=None,
    )


def _can_cfg() -> dict:
    return {
        "client": {"code": "SOC_CAN", "schema_version": "1.1"},
        "connectors": [
            {"code": "C100810", "is_credential": False, "parse_strategy": "fff"},
            {"code": "C161796", "is_credential": False, "parse_strategy": "fff"},
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C103403", "is_credential": False, "parse_strategy": "pygdsa_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# INT-1: Bureau attribution — full chain via apply_mapping()
# ---------------------------------------------------------------------------
class TestCanBureauAttributionIntegration:
    def test_transunion_and_equifax_written_to_correct_paths(self):
        tu_sf = _sf("C100810", "RESP", {"record": {"score": "720", "riskModel": "V9"}})
        efx_sf = _sf("C161796", "RESP", {"record": {"beaconScore": "680"}})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(tu_sf, efx_sf, dec_sf)
        mapping = [
            _row("bureauData.transunion.score", "C100810", "record.score"),
            _row("bureauData.transunion.riskModel", "C100810", "record.riskModel"),
            _row("bureauData.equifax.beaconScore", "C161796", "record.beaconScore"),
        ]
        apply_mapping(rec, mapping, _can_cfg())
        assert _get_path(rec.record, "bureauData.transunion.score") == "720"
        assert _get_path(rec.record, "bureauData.transunion.riskModel") == "V9"
        assert _get_path(rec.record, "bureauData.equifax.beaconScore") == "680"

    def test_bureau_providers_lineage_has_both(self):
        tu_sf = _sf("C100810", "RESP", {"record": {"score": "720"}})
        efx_sf = _sf("C161796", "RESP", {"record": {"beaconScore": "680"}})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(tu_sf, efx_sf, dec_sf)
        mapping = [
            _row("bureauData.transunion.score", "C100810", "record.score"),
        ]
        apply_mapping(rec, mapping, _can_cfg())
        providers = rec.lineage.get("bureau_providers", [])
        assert "transunion" in providers
        assert "equifax" in providers

    def test_d09_guard_no_fields_at_bureau_root(self):
        tu_sf = _sf("C100810", "RESP", {"record": {"score": "720"}})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(tu_sf, dec_sf)
        mapping = [
            _row("bureauData.transunion.score", "C100810", "record.score"),
        ]
        apply_mapping(rec, mapping, _can_cfg())
        bureau = rec.record.get("bureauData", {})
        assert "score" not in bureau   # must not be at root

    def test_d09_guard_raises_on_root_injection(self):
        from scripts.ingest_lib import _set_path
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(dec_sf)
        _set_path(rec.record, "bureauData.orphan", "bad")
        with pytest.raises(ValueError, match="D-09"):
            apply_mapping(rec, [], _can_cfg())


# ---------------------------------------------------------------------------
# INT-2: FFF connectors quarantined (INV-13)
# ---------------------------------------------------------------------------
class TestFffQuarantineIntegration:
    def test_c100810_quarantines_record(self):
        fff_sf = _sf("C100810", "RESP", None)  # payload None — fff parse fails
        rec = _rec(fff_sf)
        _handle_fff_quarantine(fff_sf, rec)
        assert rec.quarantined is True
        assert rec.lineage.get("fff_parse_blocked") is True
        assert "fff_parse_blocked" in rec.validation_failures

    def test_c161796_quarantines_record(self):
        fff_sf = _sf("C161796", "RESP", None)
        rec = _rec(fff_sf)
        _handle_fff_quarantine(fff_sf, rec)
        assert rec.quarantined is True

    def test_fff_quarantine_does_not_propagate_payload(self):
        fff_sf = _sf("C100810", "RESP", {"some": "data"})
        rec = _rec(fff_sf)
        _handle_fff_quarantine(fff_sf, rec)
        assert fff_sf.payload is None   # payload scrubbed


# ---------------------------------------------------------------------------
# INT-3: Decision extraction on CAN record (C238743-RESP, D-04)
# ---------------------------------------------------------------------------
class TestCanDecisionExtraction:
    def test_can_decision_extracted(self):
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APP"}})
        rec = _rec(dec_sf)
        apply_mapping(rec, [], _can_cfg())
        assert _get_path(rec.record, "system.application.decision") == "APP"

    def test_can_audit_folder_decision_ignored(self):
        audit_sf = _sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}},
                       folder="audit")
        rec = _rec(audit_sf)
        apply_mapping(rec, [], _can_cfg())
        assert _get_path(rec.record, "system.application.decision") is None
        assert rec.lineage.get("decision_missing") is True


# ---------------------------------------------------------------------------
# INT-4: ExtraColumns routing on CAN records
# ---------------------------------------------------------------------------
class TestCanExtraColumnsRouting:
    def test_double_parsed_field_to_extra_columns(self):
        sf = _sf("C225334", "RESP", {
            "DerivedApplicationRecord": [{"Payload": '{"appData": "value123"}'}]
        })
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(sf, dec_sf)
        mapping = [
            MappingRow(
                sdd_path="extra_columns.SOC_derived_application",
                category="ExtraColumn", data_type="object", pii=False,
                sources=[{"tier": "PRIMARY",
                          "locator": "C225334 | raw | RESP",
                          "path": "DerivedApplicationRecord.0.Payload"}],
                transform="json_double_parse", construction=None,
            )
        ]
        apply_mapping(rec, mapping, _can_cfg())
        assert rec.extra_columns.get("SOC_derived_application") == {"appData": "value123"}
        assert "extra_columns" not in rec.record

    def test_pygdsa_attrs_to_extra_columns(self):
        sf = _sf("C103403", "RESP", {"EcsDebtorNumber": "12345", "status": "active"})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(sf, dec_sf)
        mapping = [
            MappingRow(
                sdd_path="extra_columns.SOC_pygdsa_attributes.status",
                category="ExtraColumn", data_type="string", pii=False,
                sources=[{"tier": "PRIMARY",
                          "locator": "C103403 | raw | RESP",
                          "path": "status"}],
                transform=None, construction=None,
            )
        ]
        apply_mapping(rec, mapping, _can_cfg())
        assert rec.extra_columns.get("SOC_pygdsa_attributes", {}).get("status") == "active"
