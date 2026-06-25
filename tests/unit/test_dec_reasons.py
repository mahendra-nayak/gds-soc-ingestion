"""
tests/unit/test_dec_reasons.py — TASK-5.4
Unit tests for Dec_Reasons pipe-split mapping and D-03 decline completeness.

Source: C225334-RESP record.Dec_Reasons (pipe-delimited)
Target: system.application.decisionSummary.reasonCodes[]
Transform: split_on_delim (delimiter='|')

D-03: DECLINED + len(reasonCodes)==0 → REQ-BL-001 soft-warn (not a quarantine).
      APPROVED (any non-DECLINED) + empty codes → no REQ-BL-001.

TC-1: Pipe-delimited Dec_Reasons split correctly
TC-2: DECLINED + empty reason codes → REQ-BL-001 soft-warn
TC-3: Non-DECLINED + empty reason codes → no REQ-BL-001
TC-4: DECLINED + populated reason codes → no REQ-BL-001
TC-5: Dec_Description and Stipulations mapped through same mechanism
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _check_decline_completeness,
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


def _split_row(sdd_path: str, connector: str, field_path: str) -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Decision",
        data_type="array",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | raw | RESP",
            "path": field_path,
        }],
        transform="split_on_delim",
        construction=None,
    )


def _str_row(sdd_path: str, connector: str, field_path: str) -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Decision",
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
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# TC-1: Pipe-split
# ---------------------------------------------------------------------------
class TestPipeSplit:
    def test_three_codes_split_to_list(self):
        sf = _make_sf("C225334", "RESP", {"record": {"Dec_Reasons": "CODE1|CODE2|CODE3"}})
        # also need a C238743-RESP so _extract_decision doesn't flag REQ-VAL-006
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _split_row(
                "system.application.decisionSummary.reasonCodes",
                "C225334",
                "record.Dec_Reasons",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.reasonCodes")
        assert result == ["CODE1", "CODE2", "CODE3"]

    def test_single_code_split_to_list_of_one(self):
        sf = _make_sf("C225334", "RESP", {"record": {"Dec_Reasons": "REQ-BL-999"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _split_row(
                "system.application.decisionSummary.reasonCodes",
                "C225334",
                "record.Dec_Reasons",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.reasonCodes")
        assert result == ["REQ-BL-999"]

    def test_spaces_around_pipes_stripped(self):
        sf = _make_sf("C225334", "RESP", {"record": {"Dec_Reasons": " A | B | C "}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _split_row(
                "system.application.decisionSummary.reasonCodes",
                "C225334",
                "record.Dec_Reasons",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.reasonCodes")
        assert result == ["A", "B", "C"]

    def test_empty_segments_filtered_out(self):
        sf = _make_sf("C225334", "RESP", {"record": {"Dec_Reasons": "CODE1||CODE2"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _split_row(
                "system.application.decisionSummary.reasonCodes",
                "C225334",
                "record.Dec_Reasons",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.reasonCodes")
        assert result == ["CODE1", "CODE2"]


# ---------------------------------------------------------------------------
# TC-2: DECLINED + empty codes → REQ-BL-001 soft-warn (D-03)
# ---------------------------------------------------------------------------
class TestDeclinedNoReason:
    def test_declined_empty_codes_appends_req_bl_001(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "DECLINED")
        # reasonCodes not set → empty
        _check_decline_completeness(rec)
        assert "REQ-BL-001" in rec.validation_failures

    def test_declined_empty_codes_sets_lineage_flag(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "DECLINED")
        _check_decline_completeness(rec)
        assert rec.lineage.get("reason_codes_missing") is True

    def test_declined_empty_codes_does_not_quarantine(self):
        """D-03: soft-warn only — quarantine must NOT be set."""
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "DECLINED")
        _check_decline_completeness(rec)
        assert not rec.quarantined

    def test_declined_case_insensitive(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "declined")
        _check_decline_completeness(rec)
        assert "REQ-BL-001" in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-3: Non-DECLINED + empty codes → no REQ-BL-001
# ---------------------------------------------------------------------------
class TestNonDeclinedNoReason:
    def test_approved_empty_codes_no_req_bl_001(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "APPROVED")
        _check_decline_completeness(rec)
        assert "REQ-BL-001" not in rec.validation_failures

    def test_app_empty_codes_no_req_bl_001(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "APP")
        _check_decline_completeness(rec)
        assert "REQ-BL-001" not in rec.validation_failures

    def test_no_decision_no_req_bl_001(self):
        rec = _make_rec()
        # decision not set at all
        _check_decline_completeness(rec)
        assert "REQ-BL-001" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-4: DECLINED with populated reason codes → no REQ-BL-001
# ---------------------------------------------------------------------------
class TestDeclinedWithReason:
    def test_declined_with_codes_no_req_bl_001(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "DECLINED")
        _set_path(rec.record, "system.application.decisionSummary.reasonCodes", ["CODE1", "CODE2"])
        _check_decline_completeness(rec)
        assert "REQ-BL-001" not in rec.validation_failures

    def test_declined_with_codes_no_lineage_flag(self):
        rec = _make_rec()
        _set_path(rec.record, "system.application.decision", "DECLINED")
        _set_path(rec.record, "system.application.decisionSummary.reasonCodes", ["X"])
        _check_decline_completeness(rec)
        assert not rec.lineage.get("reason_codes_missing")


# ---------------------------------------------------------------------------
# TC-5: Dec_Description and Stipulations mapped via same mechanism
# ---------------------------------------------------------------------------
class TestDecDescriptionAndStipulations:
    def test_dec_description_written_to_record(self):
        sf = _make_sf("C225334", "RESP", {"record": {"Dec_Description": "Manual review required"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _str_row(
                "system.application.decisionSummary.description",
                "C225334",
                "record.Dec_Description",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        assert (
            _get_path(rec.record, "system.application.decisionSummary.description")
            == "Manual review required"
        )

    def test_stipulations_split_to_list(self):
        sf = _make_sf(
            "C225334", "RESP", {"record": {"Stipulations": "Proof of income|Bank statement"}}
        )
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}}, folder="raw")
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _split_row(
                "system.application.decisionSummary.stipulations",
                "C225334",
                "record.Stipulations",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.stipulations")
        assert result == ["Proof of income", "Bank statement"]
