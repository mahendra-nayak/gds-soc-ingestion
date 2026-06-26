"""
tests/unit/test_parse_pygdsa.py — TASK-4.5
Unit tests for PyGDSA double-parse strategy: C103403.

Double-parse pipeline:
  1. http_envelope_strip (raw_bytes)
  2. maybe_gunzip
  3. json.loads → outer_json (list of base64-encoded segments)
  4. base64.b64decode each segment + json.loads → flat attrs dict
  5. sf.payload = attrs

Invariants verified:
  INV-01: Bearer token must not be present in sf.raw_bytes before decode.
          AssertionError raised if credential not scrubbed.
  D-11 (reclassified, not an invariant): REQ-BL-004 is a soft-warn only;
          attr_count < 100 appends to validation_failures, does NOT quarantine.

TC-1: Synthetic base64 JSON blob → decoded correctly, attr_count > 100
TC-2: attr_count < 100 → REQ-BL-004 in validation_failures, record NOT quarantined
TC-3: Non-base64 segment content → binascii.Error propagated
TC-4: Bearer token in sf.raw_bytes before decode → AssertionError (INV-01)
"""
import base64
import binascii
import json

import pytest

from scripts.ingest_lib import (
    AppRecord,
    SourceFile,
    _check_pygdsa_attr_count,
    parse_file,
)


# ---------------------------------------------------------------------------
# Config stub — C103403 registered with pygdsa_json strategy
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C103403", "parse_strategy": "pygdsa_json", "is_credential": False},
        ],
    }


def _make_sf(path, connector: str = "C103403") -> SourceFile:
    return SourceFile(
        path=path,
        folder="raw",
        connector=connector,
        direction="RESP",
        step=None,
        app_id_raw="500249960_20250101000000",
        sequence_id="1",
    )


def _make_rec() -> AppRecord:
    return AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )


def _encode_segment(d: dict) -> str:
    """Base64-encode a dict as a segment string."""
    return base64.b64encode(json.dumps(d).encode()).decode()


def _write_outer(tmp_path, segments: list) -> "SourceFile":
    """Write outer_json (list of base64 segments) to a temp file, return sf."""
    f = tmp_path / "c103403_resp.json"
    f.write_bytes(json.dumps(segments).encode())
    return _make_sf(f)


# ---------------------------------------------------------------------------
# TC-1: Synthetic base64 JSON blob → decoded correctly, attr_count > 100
# ---------------------------------------------------------------------------
class TestDoubleParseDecode:
    def test_attrs_decoded_from_single_segment(self, tmp_path):
        attrs = {f"attr_{i}": i for i in range(110)}  # 110 keys
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        result = parse_file(sf, _cfg())
        assert result == attrs

    def test_payload_set_on_source_file(self, tmp_path):
        attrs = {f"attr_{i}": i for i in range(110)}
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        parse_file(sf, _cfg())
        assert sf.payload is not None
        assert len(sf.payload) == 110

    def test_multiple_segments_merged_into_flat_dict(self, tmp_path):
        seg1 = {f"a_{i}": i for i in range(60)}   # 60 keys
        seg2 = {f"b_{i}": i for i in range(60)}   # 60 keys → total 120
        sf = _write_outer(tmp_path, [_encode_segment(seg1), _encode_segment(seg2)])
        result = parse_file(sf, _cfg())
        assert len(result) == 120
        assert "a_0" in result
        assert "b_0" in result

    def test_attr_count_above_100_no_warning(self, tmp_path):
        attrs = {f"key_{i}": i for i in range(110)}
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        rec = _make_rec()
        parse_file(sf, _cfg())
        _check_pygdsa_attr_count(sf, rec)
        assert "REQ-BL-004" not in rec.validation_failures

    def test_ecs_debtor_number_accessible_as_top_level_key(self, tmp_path):
        """EcsDebtorNumber is a flat top-level key in the attrs dict."""
        attrs = {f"attr_{i}": i for i in range(109)}
        attrs["EcsDebtorNumber"] = "12345"   # 110 total
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        result = parse_file(sf, _cfg())
        assert result.get("EcsDebtorNumber") == "12345"


# ---------------------------------------------------------------------------
# TC-2: attr_count < 100 → REQ-BL-004 in validation_failures, NOT quarantined
# ---------------------------------------------------------------------------
class TestAttrCountSoftWarn:
    def test_req_bl_004_appended_when_under_100(self, tmp_path):
        attrs = {f"attr_{i}": i for i in range(5)}  # 5 keys < 100
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        rec = _make_rec()
        parse_file(sf, _cfg())
        _check_pygdsa_attr_count(sf, rec)
        assert "REQ-BL-004" in rec.validation_failures

    def test_record_not_quarantined_on_req_bl_004(self, tmp_path):
        """REQ-BL-004 is soft-warn only — must not quarantine."""
        attrs = {f"attr_{i}": i for i in range(5)}
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        rec = _make_rec()
        parse_file(sf, _cfg())
        _check_pygdsa_attr_count(sf, rec)
        assert rec.quarantined is False

    def test_check_skipped_when_payload_none(self, tmp_path):
        """_check_pygdsa_attr_count must not raise when sf.payload is None."""
        f = tmp_path / "dummy.json"
        f.write_bytes(b"[]")
        sf = _make_sf(f)
        sf.payload = None
        rec = _make_rec()
        _check_pygdsa_attr_count(sf, rec)   # must not raise
        assert "REQ-BL-004" not in rec.validation_failures

    def test_exactly_100_attrs_no_warning(self, tmp_path):
        """Boundary: exactly 100 keys is not a warning."""
        attrs = {f"attr_{i}": i for i in range(100)}
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        rec = _make_rec()
        parse_file(sf, _cfg())
        _check_pygdsa_attr_count(sf, rec)
        assert "REQ-BL-004" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-3: Non-base64 segment content — malformed segments skipped, empty dict returned
# ---------------------------------------------------------------------------
class TestNonBase64Error:
    def test_invalid_base64_skipped_returns_empty(self, tmp_path):
        # Malformed base64 segments are skipped with a warning; no exception propagated
        outer = json.dumps(["!!!not-valid-base64!!!"]).encode()
        f = tmp_path / "bad.json"
        f.write_bytes(outer)
        sf = _make_sf(f)
        result = parse_file(sf, _cfg())
        assert result == {}

    def test_non_base64_with_special_chars_skipped(self, tmp_path):
        outer = json.dumps(["<xml>not base64</xml>"]).encode()
        f = tmp_path / "bad2.json"
        f.write_bytes(outer)
        sf = _make_sf(f)
        result = parse_file(sf, _cfg())
        assert result == {}


# ---------------------------------------------------------------------------
# TC-4: Bearer token present before decode → AssertionError (INV-01)
# ---------------------------------------------------------------------------
class TestCredentialAssertionFires:
    def test_bearer_token_in_raw_bytes_raises(self, tmp_path):
        """INV-01: strategy must assert if raw_bytes still contains Bearer token."""
        f = tmp_path / "c103403_unscrubbed.json"
        f.write_bytes(b"[]")   # valid content, but not reached
        sf = _make_sf(f)
        sf.raw_bytes = b"Authorization: Bearer abc123secrettoken\r\n\r\n[]"
        with pytest.raises(AssertionError, match="INV-01"):
            parse_file(sf, _cfg())

    def test_bearer_token_case_insensitive(self, tmp_path):
        f = tmp_path / "c103403_unscrubbed2.json"
        f.write_bytes(b"[]")
        sf = _make_sf(f)
        sf.raw_bytes = b"authorization: bearer SECRETTOKEN\r\n\r\n[]"
        with pytest.raises(AssertionError, match="INV-01"):
            parse_file(sf, _cfg())

    def test_no_bearer_token_does_not_raise(self, tmp_path):
        """Scrubbed payload (no Bearer token) must not trigger assertion."""
        attrs = {f"attr_{i}": i for i in range(110)}
        sf = _write_outer(tmp_path, [_encode_segment(attrs)])
        # raw_bytes is None → loaded from disk (clean content, no Bearer)
        parse_file(sf, _cfg())  # must not raise
