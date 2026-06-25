"""
tests/unit/test_parse_fff_stub.py — TASK-4.3
Unit tests for FFF parse strategy stub: C100810 (TransUnion CAN).

Invariants verified:
  INV-13: Required bureau evidence may not silently degrade into a valid output record.
          FFF parse failure = hard quarantine. Silent skip is not permitted.
  CLAUDE.md: FFF parser is stub only — raises NotImplementedError with TODO(Q-FFF).
             Do not implement FFF parser body.

TC-1: _parse_fff raises NotImplementedError with Q-FFF marker
TC-2: parse_file with C100810 (fff strategy) raises NotImplementedError
TC-3: _handle_fff_quarantine sets sf.payload=None, quarantines rec, writes lineage
TC-4: fff_parse_blocked present in rec.validation_failures
TC-5: rec.quarantined = True after _handle_fff_quarantine
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import (
    AppRecord,
    SourceFile,
    _handle_fff_quarantine,
    parse_file,
)


# ---------------------------------------------------------------------------
# Config stub — C100810 registered with fff parse strategy
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    return {
        "client": {"code": "SOC_CAN", "schema_version": "1.1"},
        "connectors": [
            {"code": "C100810", "parse_strategy": "fff", "is_credential": False},
        ],
    }


def _make_sf(path: Path, connector: str = "C100810") -> SourceFile:
    return SourceFile(
        path=path,
        folder="data",
        connector=connector,
        direction="RESP",
        step=None,
        app_id_raw="600249960_20250101000000",
        sequence_id="1",
    )


def _make_rec() -> AppRecord:
    return AppRecord(
        app_id_canonical="600249960_20250101000000",
        app_id_raw="600249960_20250101000000",
        geography="CAN",
    )


# ---------------------------------------------------------------------------
# TC-1: _parse_fff raises NotImplementedError with Q-FFF marker
# ---------------------------------------------------------------------------
class TestFffStubRaises:
    def test_parse_fff_raises_not_implemented(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"FFF_PAYLOAD")
        sf = _make_sf(f)
        with pytest.raises(NotImplementedError):
            parse_file(sf, _cfg())

    def test_error_message_contains_q_fff(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"FFF_PAYLOAD")
        sf = _make_sf(f)
        with pytest.raises(NotImplementedError, match="Q-FFF"):
            parse_file(sf, _cfg())

    def test_error_message_contains_connector_code(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"FFF_PAYLOAD")
        sf = _make_sf(f)
        with pytest.raises(NotImplementedError, match="C100810"):
            parse_file(sf, _cfg())

    def test_payload_not_set_after_failed_parse(self, tmp_path):
        """sf.payload must remain None — the parse never completed."""
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"FFF_PAYLOAD")
        sf = _make_sf(f)
        try:
            parse_file(sf, _cfg())
        except NotImplementedError:
            pass
        assert sf.payload is None


# ---------------------------------------------------------------------------
# TC-2: parse_file raises NotImplementedError for any file content
# ---------------------------------------------------------------------------
class TestParseFileRaisesForFff:
    def test_empty_file_still_raises(self, tmp_path):
        f = tmp_path / "empty.fff"
        f.write_bytes(b"")
        sf = _make_sf(f)
        with pytest.raises(NotImplementedError):
            parse_file(sf, _cfg())

    def test_non_empty_file_raises(self, tmp_path):
        f = tmp_path / "data.fff"
        f.write_bytes(b"ABCDEF" * 100)
        sf = _make_sf(f)
        with pytest.raises(NotImplementedError):
            parse_file(sf, _cfg())


# ---------------------------------------------------------------------------
# TC-3: _handle_fff_quarantine sets sf.payload=None, lineage, quarantine flag
# ---------------------------------------------------------------------------
class TestHandleFffQuarantine:
    def test_payload_set_to_none(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        sf.payload = "stale"   # simulate any prior value
        rec = _make_rec()
        _handle_fff_quarantine(sf, rec)
        assert sf.payload is None

    def test_fff_parse_blocked_in_lineage(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        rec = _make_rec()
        _handle_fff_quarantine(sf, rec)
        assert rec.lineage.get("fff_parse_blocked") is True


# ---------------------------------------------------------------------------
# TC-4: fff_parse_blocked in validation_failures (INV-13)
# ---------------------------------------------------------------------------
class TestFffValidationFailures:
    def test_fff_parse_blocked_in_failures(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        rec = _make_rec()
        _handle_fff_quarantine(sf, rec)
        assert "fff_parse_blocked" in rec.validation_failures

    def test_failure_not_duplicated_on_single_call(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        rec = _make_rec()
        _handle_fff_quarantine(sf, rec)
        count = rec.validation_failures.count("fff_parse_blocked")
        assert count == 1


# ---------------------------------------------------------------------------
# TC-5: rec.quarantined = True after _handle_fff_quarantine (INV-13)
# ---------------------------------------------------------------------------
class TestFffQuarantineFlag:
    def test_record_quarantined_true(self, tmp_path):
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        rec = _make_rec()
        assert rec.quarantined is False  # pre-condition
        _handle_fff_quarantine(sf, rec)
        assert rec.quarantined is True

    def test_quarantine_is_hard_not_soft(self, tmp_path):
        """INV-13: quarantined must be True (bool), not a soft warning signal."""
        f = tmp_path / "c100810.fff"
        f.write_bytes(b"x")
        sf = _make_sf(f)
        rec = _make_rec()
        _handle_fff_quarantine(sf, rec)
        assert rec.quarantined is True
        assert isinstance(rec.quarantined, bool)
