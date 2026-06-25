"""
tests/unit/test_debtor_consistency.py — TASK-3.5
Unit tests for EcsDebtorNumber cross-session consistency check
in _check_payload_debtor_consistency() and _extract_ecs_debtor().

D-02 (payload-level): EcsDebtorNumber must be identical across all sessions
for a CAN AppRecord. Mismatch → rec.quarantined=True, 'D-02-payload-debtor-mismatch'.

TC-1: All sessions same debtor → no quarantine
TC-2: Two sessions with different debtors → quarantined, D-02 failure recorded
TC-3: No debtor in any payload (sf.payload is None or field absent) → no quarantine
TC-4: C225334-REQ payload extraction
TC-5: C103403-RESP payload extraction
TC-6: data/ folder payload extraction
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import AppRecord, SourceFile
from scripts.ingest_lib import _check_payload_debtor_consistency, _extract_ecs_debtor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_sf(connector: str, direction: str = "REQ", folder: str = "raw",
             payload: dict | None = None) -> SourceFile:
    sf = SourceFile(
        path=Path(f"fake/{folder}/{connector}_{direction}.txt"),
        folder=folder,
        connector=connector,
        direction=direction,
        step=None,
        app_id_raw="600249966_20250101000000",
        sequence_id="1",
        geography="CAN",
    )
    sf.payload = payload
    return sf


def _make_rec(*files: SourceFile) -> AppRecord:
    rec = AppRecord("600249966_20250101000000", "600249966_20250101000000",
                    geography="CAN")
    rec.files = list(files)
    return rec


# ---------------------------------------------------------------------------
# TC-1: All sessions same debtor → no quarantine
# ---------------------------------------------------------------------------
class TestSameDebtorAllSessions:
    def test_same_debtor_not_quarantined(self):
        sf1 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "500249966"}})
        sf2 = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "500249966"})
        rec = _make_rec(sf1, sf2)
        _check_payload_debtor_consistency(rec)
        assert rec.quarantined is False

    def test_no_d02_failure_same_debtor(self):
        sf1 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "500249966"}})
        sf2 = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "500249966"})
        rec = _make_rec(sf1, sf2)
        _check_payload_debtor_consistency(rec)
        assert "D-02-payload-debtor-mismatch" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-2: Two sessions with different debtors → quarantined, D-02 recorded
# ---------------------------------------------------------------------------
class TestDifferentDebtors:
    def test_quarantined_on_mismatch(self):
        sf1 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "500249966"}})
        sf2 = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "999999999"})
        rec = _make_rec(sf1, sf2)
        _check_payload_debtor_consistency(rec)
        assert rec.quarantined is True

    def test_d02_failure_recorded(self):
        sf1 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "AAA"}})
        sf2 = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "BBB"})
        rec = _make_rec(sf1, sf2)
        _check_payload_debtor_consistency(rec)
        assert "D-02-payload-debtor-mismatch" in rec.validation_failures

    def test_three_sessions_mismatch(self):
        sf1 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "111"}})
        sf2 = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "222"})
        sf3 = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "111"}}, folder="raw")
        rec = _make_rec(sf1, sf2, sf3)
        _check_payload_debtor_consistency(rec)
        assert rec.quarantined is True


# ---------------------------------------------------------------------------
# TC-3: No debtor in payloads → no quarantine (graceful skip)
# ---------------------------------------------------------------------------
class TestNoDebtorInPayloads:
    def test_no_payload_no_quarantine(self):
        sf = _make_sf("C225334", "REQ", payload=None)
        rec = _make_rec(sf)
        _check_payload_debtor_consistency(rec)
        assert rec.quarantined is False

    def test_payload_without_debtor_field_no_quarantine(self):
        sf = _make_sf("C225334", "REQ", payload={"record": {"OtherField": "value"}})
        rec = _make_rec(sf)
        _check_payload_debtor_consistency(rec)
        assert rec.quarantined is False

    def test_no_error_on_all_none_payloads(self):
        files = [_make_sf("C225334", "REQ", payload=None) for _ in range(3)]
        rec = _make_rec(*files)
        _check_payload_debtor_consistency(rec)  # must not raise


# ---------------------------------------------------------------------------
# TC-4: C225334-REQ payload extraction
# ---------------------------------------------------------------------------
class TestC225334Extraction:
    def test_extracts_from_record_path(self):
        sf = _make_sf("C225334", "REQ", payload={"record": {"EcsDebtorNumber": "500249966"}})
        result = _extract_ecs_debtor(sf)
        assert result == "500249966"

    def test_none_when_record_key_absent(self):
        sf = _make_sf("C225334", "REQ", payload={"other": {}})
        assert _extract_ecs_debtor(sf) is None

    def test_none_for_c225334_resp(self):
        """RESP direction for C225334 uses different extraction path."""
        sf = _make_sf("C225334", "RESP", payload={"record": {"EcsDebtorNumber": "123"}})
        # C225334-RESP does not match the C225334-REQ rule; should return None
        assert _extract_ecs_debtor(sf) is None


# ---------------------------------------------------------------------------
# TC-5: C103403-RESP payload extraction
# ---------------------------------------------------------------------------
class TestC103403Extraction:
    def test_extracts_from_flat_attrs_dict(self):
        # pygdsa_json yields a flat attrs dict; EcsDebtorNumber is a top-level key
        sf = _make_sf("C103403", "RESP", payload={"EcsDebtorNumber": "600249966"})
        result = _extract_ecs_debtor(sf)
        assert result == "600249966"

    def test_none_when_attributes_key_absent(self):
        sf = _make_sf("C103403", "RESP", payload={"data": {"EcsDebtorNumber": "123"}})
        assert _extract_ecs_debtor(sf) is None

    def test_none_when_payload_none(self):
        sf = _make_sf("C103403", "RESP", payload=None)
        assert _extract_ecs_debtor(sf) is None


# ---------------------------------------------------------------------------
# TC-6: data/ folder payload extraction
# ---------------------------------------------------------------------------
class TestDataFolderExtraction:
    def test_extracts_from_data_path(self):
        """data/ tier extraction applies to connectors not covered by explicit rules."""
        sf = _make_sf("C161796", "REQ", folder="data",
                      payload={"data": {"EcsDebtorNumber": "700249966"}})
        result = _extract_ecs_debtor(sf)
        assert result == "700249966"

    def test_none_when_data_key_absent(self):
        sf = _make_sf("C161796", "REQ", folder="data", payload={"other": {}})
        assert _extract_ecs_debtor(sf) is None

    def test_raw_folder_non_explicit_connector_returns_none(self):
        """raw/ folder for non-C225334/C103403 connector — no extraction rule → None."""
        sf = _make_sf("C161796", "REQ", folder="raw",
                      payload={"data": {"EcsDebtorNumber": "SHOULD_NOT_MATCH"}})
        result = _extract_ecs_debtor(sf)
        assert result is None
