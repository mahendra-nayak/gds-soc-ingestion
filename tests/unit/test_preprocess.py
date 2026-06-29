"""
tests/unit/test_preprocess.py — TASK-2.4
Unit tests for pre-processing functions: http_envelope_strip, maybe_gunzip,
normalise_encoding.

TC-1 (http_envelope_strip): headers present → body only returned
TC-2 (http_envelope_strip): no CRLFCRLF separator → input returned unchanged
TC-3 (http_envelope_strip): multiple CRLFCRLF in body → only first split applied
TC-4 (maybe_gunzip): gzipped content → decompressed bytes returned
TC-5 (maybe_gunzip): non-gzipped content → input returned unchanged
TC-6 (maybe_gunzip): empty bytes → returned unchanged, no exception
TC-7 (normalise_encoding): valid UTF-8 body → returned as UTF-8 bytes
TC-8 (normalise_encoding): ISO-8859-1 body (invalid UTF-8) → re-encoded to UTF-8
TC-9 (normalise_encoding): body undecodable as UTF-8 or ISO-8859-1 → ValueError with connector code
TC-10 (normalise_encoding): connector code appears in ValueError message
"""
import gzip
import pytest

from scripts.ingest_lib import http_envelope_strip, maybe_gunzip, normalise_encoding, _to_utc_iso


# ---------------------------------------------------------------------------
# TC-1 / TC-2 / TC-3 — http_envelope_strip
# ---------------------------------------------------------------------------
class TestHttpEnvelopeStrip:
    def test_body_extracted_after_crlfcrlf(self):
        raw = b"HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n{\"key\": \"val\"}"
        result = http_envelope_strip(raw)
        assert result == b'{"key": "val"}'

    def test_no_separator_returns_input_unchanged(self):
        raw = b"no separator here just body content"
        assert http_envelope_strip(raw) == raw

    def test_empty_body_after_separator(self):
        raw = b"Header: val\r\n\r\n"
        assert http_envelope_strip(raw) == b""

    def test_multiple_crlfcrlf_only_first_split(self):
        """Body itself may contain CRLFCRLF; only the first split is applied."""
        raw = b"Header: h\r\n\r\nbody\r\n\r\nmore"
        result = http_envelope_strip(raw)
        assert result == b"body\r\n\r\nmore"

    def test_multiline_headers_stripped(self):
        raw = (
            b"POST /api HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Authorization: Bearer [REDACTED]\r\n"
            b"\r\n"
            b"actual body content"
        )
        result = http_envelope_strip(raw)
        assert result == b"actual body content"

    def test_lf_only_separator_extracted(self):
        """BUG-02: C225334 response files use LF-only (\\n\\n) instead of CRLFCRLF."""
        raw = b"HTTP Code: 200\nHTTP Headers:\n\n{\"record\": 1}"
        result = http_envelope_strip(raw)
        assert result == b'{"record": 1}'

    def test_returns_bytes(self):
        raw = b"H: v\r\n\r\nbody"
        assert isinstance(http_envelope_strip(raw), bytes)


# ---------------------------------------------------------------------------
# TC-4 / TC-5 / TC-6 — maybe_gunzip
# ---------------------------------------------------------------------------
class TestMaybeGunzip:
    def test_gzipped_content_decompressed(self):
        original = b"hello compressed world"
        compressed = gzip.compress(original)
        assert compressed[:2] == b"\x1f\x8b", "Test fixture must produce gzip magic bytes"
        result = maybe_gunzip(compressed)
        assert result == original

    def test_non_gzipped_content_unchanged(self):
        raw = b"plain text content, not gzipped"
        assert maybe_gunzip(raw) == raw

    def test_json_body_unchanged(self):
        raw = b'{"key": "value"}'
        assert maybe_gunzip(raw) == raw

    def test_empty_bytes_unchanged(self):
        assert maybe_gunzip(b"") == b""

    def test_magic_bytes_check_is_exact(self):
        """Bytes starting with 0x1f but not 0x8b must NOT be treated as gzip."""
        raw = b"\x1f\x00some data"
        assert maybe_gunzip(raw) == raw

    def test_returns_bytes(self):
        assert isinstance(maybe_gunzip(b"plain"), bytes)


# ---------------------------------------------------------------------------
# TC-7 / TC-8 / TC-9 / TC-10 — normalise_encoding
# ---------------------------------------------------------------------------
class TestNormaliseEncoding:
    def test_valid_utf8_returned_as_utf8(self):
        body = "hello UTF-8 content".encode("utf-8")
        result = normalise_encoding(body, "C103403")
        assert result == body

    def test_utf8_with_multibyte_chars(self):
        body = "café résumé".encode("utf-8")
        result = normalise_encoding(body, "C103403")
        assert result == body

    def test_iso8859_body_re_encoded_to_utf8(self):
        """ISO-8859-1 byte sequence that is invalid as UTF-8 must be normalised."""
        # 'é' in ISO-8859-1 is 0xE9 — invalid as a lone byte in UTF-8
        iso_body = "caf\xe9".encode("iso-8859-1")
        result = normalise_encoding(iso_body, "C754889")
        # Result should be the UTF-8 encoding of 'café'
        assert result == "café".encode("utf-8")

    def test_iso8859_round_trip_is_valid_utf8(self):
        iso_body = "r\xe9sum\xe9".encode("iso-8859-1")  # 'résumé' in ISO-8859-1
        result = normalise_encoding(iso_body, "C161653")
        # Must decode cleanly as UTF-8
        decoded = result.decode("utf-8")
        assert decoded == "résumé"

    def test_undecodable_body_raises_value_error(self):
        """Non-ASCII bytes with target='ascii' raise ValueError with connector code."""
        # ISO-8859-1 decodes any byte, but re-encoding to ASCII fails for non-ASCII
        # chars — our implementation wraps this as ValueError.
        iso_body = "caf\xe9".encode("iso-8859-1")  # é not representable in ASCII
        with pytest.raises(ValueError):
            normalise_encoding(iso_body, "C103403", target="ascii")

    def test_connector_code_in_error_message(self):
        """ValueError must include the connector code for traceability (TC-10)."""
        # Force encode failure by using target='ascii' with non-ASCII ISO-8859-1 bytes
        iso_body = "caf\xe9".encode("iso-8859-1")  # 'é' is not ASCII-encodable
        with pytest.raises(ValueError, match="C999TEST"):
            normalise_encoding(iso_body, "C999TEST", target="ascii")

    def test_returns_bytes(self):
        result = normalise_encoding(b"hello", "C161653")
        assert isinstance(result, bytes)

    def test_target_parameter_respected(self):
        body = "hello".encode("utf-8")
        result = normalise_encoding(body, "C161653", target="utf-8")
        assert result == b"hello"


# ---------------------------------------------------------------------------
# BUG-03 — _to_utc_iso: timezone offset normalisation and naive datetime fix
# ---------------------------------------------------------------------------
class TestToUtcIso:
    def test_offset_no_colon_normalised(self):
        """BUG-03a: +HHMM (no colon) must be accepted and converted to UTC ISO."""
        result = _to_utc_iso("2025-04-22T11:06:40+0000")
        assert result is not None
        assert result.startswith("2025-04-22T11:06:40")

    def test_offset_with_colon_accepted(self):
        result = _to_utc_iso("2025-04-22T11:06:40+00:00")
        assert result is not None
        assert result.startswith("2025-04-22T11:06:40")

    def test_compact_datetime_format(self):
        """YYYYMMDDHHMMSS strptime format."""
        result = _to_utc_iso("20250422110640")
        assert result is not None
        assert "2025-04-22" in result
        assert "11:06:40" in result

    def test_us_date_format(self):
        """MM/DD/YYYY strptime format."""
        result = _to_utc_iso("04/22/2025")
        assert result is not None
        assert "2025-04-22" in result

    def test_naive_datetime_hour_preserved(self):
        """BUG-03b: naive datetime must get UTC assigned, not shifted by local tz."""
        result = _to_utc_iso("2025-04-22T11:06:40")
        assert result is not None
        # Hour must be 11, not shifted by the local timezone offset.
        assert result.startswith("2025-04-22T11:06:40")

    def test_unrecognised_format_returns_none(self):
        assert _to_utc_iso("not-a-date") is None
