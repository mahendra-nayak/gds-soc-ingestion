"""
tests/integration/test_mapping_usa.py — TASK-5.5
Integration tests for apply_mapping() against a synthetic USA AppRecord.

Exercises the full chain:
  resolve_source() → _read_locator() → apply_transform() → _set_path()
  → _check_score_slot_bounds() → _check_decline_completeness()

Tests use a synthetic AppRecord assembled to resemble what run_pipeline()
produces after parse and group_by_app for a SOC_USA package.
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _get_path,
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


def _rec(*files) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    rec.files = list(files)
    return rec


def _row(sdd_path: str, connector: str, field_path: str,
         transform: str = None, folder: str = "raw") -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Attribute",
        data_type="string",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | {folder} | RESP",
            "path": field_path,
        }],
        transform=transform,
        construction=None,
    )


def _usa_cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C78098", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C78449", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C215125", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C103403", "is_credential": False, "parse_strategy": "pygdsa_json"},
            {"code": "C1677939", "is_credential": False, "parse_strategy": "xml_dict"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# Integration test 1: FICO score + decision + reason codes — full chain
# ---------------------------------------------------------------------------
class TestFullMappingChain:
    def _build_rec_and_mapping(self):
        c225334_sf = _sf("C225334", "RESP", {
            "record": {
                "FICO": "720",
                "Dec_Reasons": "CODE1|CODE2",
                "Dec_Description": "Automated decision",
            }
        })
        c238743_sf = _sf("C238743", "RESP", {
            "Decision": {"decision": "APPROVED", "interestrate": "6.9"}
        })
        rec = _rec(c225334_sf, c238743_sf)
        mapping = [
            _row("system.application.scores.score1", "C225334", "record.FICO",
                 transform="string_to_numeric"),
            MappingRow(
                sdd_path="system.application.decisionSummary.reasonCodes",
                category="Decision", data_type="array", pii=False,
                sources=[{"tier": "PRIMARY", "locator": "C225334 | raw | RESP",
                          "path": "record.Dec_Reasons"}],
                transform="split_on_delim", construction=None,
            ),
            _row("system.application.decisionSummary.description",
                 "C225334", "record.Dec_Description"),
        ]
        return rec, mapping

    def test_score1_resolved_as_int(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        assert _get_path(rec.record, "system.application.scores.score1") == 720
        assert isinstance(_get_path(rec.record, "system.application.scores.score1"), int)

    def test_decision_extracted_from_c238743(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        assert _get_path(rec.record, "system.application.decision") == "APPROVED"

    def test_apr_extracted_from_c238743(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        assert _get_path(rec.record, "system.application.apr") == "6.9"

    def test_reason_codes_split(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        result = _get_path(rec.record, "system.application.decisionSummary.reasonCodes")
        assert result == ["CODE1", "CODE2"]

    def test_description_written(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        assert (
            _get_path(rec.record, "system.application.decisionSummary.description")
            == "Automated decision"
        )

    def test_no_validation_failures_on_clean_record(self):
        rec, mapping = self._build_rec_and_mapping()
        apply_mapping(rec, mapping, _usa_cfg())
        # REQ-VAL-006 should not appear since C238743-RESP decision is present
        assert "REQ-VAL-006" not in rec.validation_failures
        assert "REQ-BL-001" not in rec.validation_failures


# ---------------------------------------------------------------------------
# Integration test 2: Source priority fallback end-to-end
# ---------------------------------------------------------------------------
class TestSourcePriorityIntegration:
    def test_secondary_used_when_primary_absent(self):
        """Primary connector absent from package → secondary provides value."""
        secondary_sf = _sf("C78098", "RESP", {"data": {"applicant_id": "APP-001"}})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(secondary_sf, dec_sf)
        mapping = [
            MappingRow(
                sdd_path="system.application.applicant_id",
                category="ID", data_type="string", pii=False,
                sources=[
                    {"tier": "PRIMARY", "locator": "C225334 | raw | RESP",
                     "path": "record.applicant_id"},
                    {"tier": "SECONDARY", "locator": "C78098 | raw | RESP",
                     "path": "data.applicant_id"},
                ],
                transform=None, construction=None,
            )
        ]
        apply_mapping(rec, mapping, _usa_cfg())
        assert _get_path(rec.record, "system.application.applicant_id") == "APP-001"

    def test_d12_primary_wins_over_richer_secondary(self):
        """D-12: PRIMARY value used even if SECONDARY has additional keys."""
        primary_sf = _sf("C225334", "RESP", {"record": {"FICO": "680"}})
        secondary_sf = _sf("C78098", "RESP", {"data": {"FICO": "720", "extra": "bonus"}})
        dec_sf = _sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _rec(primary_sf, secondary_sf, dec_sf)
        mapping = [
            MappingRow(
                sdd_path="system.application.scores.score1",
                category="Score", data_type="numeric", pii=False,
                sources=[
                    {"tier": "PRIMARY", "locator": "C225334 | raw | RESP",
                     "path": "record.FICO"},
                    {"tier": "SECONDARY", "locator": "C78098 | raw | RESP",
                     "path": "data.FICO"},
                ],
                transform="string_to_numeric", construction=None,
            )
        ]
        apply_mapping(rec, mapping, _usa_cfg())
        # PRIMARY = 680; SECONDARY = 720 — PRIMARY must win
        assert _get_path(rec.record, "system.application.scores.score1") == 680


# ---------------------------------------------------------------------------
# Integration test 3: Decline completeness end-to-end
# ---------------------------------------------------------------------------
class TestDeclineCompletenessIntegration:
    def test_declined_with_no_codes_triggers_req_bl_001(self):
        c238743_sf = _sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}})
        rec = _rec(c238743_sf)
        # No Dec_Reasons mapping row — reasonCodes never written
        apply_mapping(rec, [], _usa_cfg())
        assert "REQ-BL-001" in rec.validation_failures
        assert not rec.quarantined

    def test_declined_with_codes_no_req_bl_001(self):
        c225334_sf = _sf("C225334", "RESP", {"record": {"Dec_Reasons": "DQ1|DQ2"}})
        c238743_sf = _sf("C238743", "RESP", {"Decision": {"decision": "DECLINED"}})
        rec = _rec(c225334_sf, c238743_sf)
        mapping = [
            MappingRow(
                sdd_path="system.application.decisionSummary.reasonCodes",
                category="Decision", data_type="array", pii=False,
                sources=[{"tier": "PRIMARY", "locator": "C225334 | raw | RESP",
                          "path": "record.Dec_Reasons"}],
                transform="split_on_delim", construction=None,
            )
        ]
        apply_mapping(rec, mapping, _usa_cfg())
        assert "REQ-BL-001" not in rec.validation_failures
