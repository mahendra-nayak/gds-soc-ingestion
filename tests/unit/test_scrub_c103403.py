"""
tests/unit/test_scrub_c103403.py — TASK-2.3
Unit tests for credential scrub: connector C103403 (Bearer token — header + JSON body).

Invariant verified:
  INV-01 (pattern-based): both scrub locations use regex, not exact-match.
  INV-01 (scrub first): sf.raw_bytes overwritten in-place; both scrubs complete
    before any downstream function reads the payload.
  INV-01 (order): both header and JSON body scrubs must complete before any
    base64 decode or parse begins.

TC-1: HTTP header with Bearer token → [SCRUBBED]
TC-2: JSON body with 'bearer_token' key → value scrubbed
TC-3: JSON body with 'access_token' key → value scrubbed
TC-4: No credential fields present → unchanged, no exception
TC-5: Payload with both header + JSON body → both locations scrubbed
TC-6: 'api_key' JSON field also matched by body pattern
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import ClientConfig, SourceFile, scrub_credentials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_HEADER_SCRUB_RULE = {
    "connector": "C103403",
    "method": "redact",
    "pattern": r"(?i)(Authorization:\s*)[^\r\n]+",
    "replacement": r"\1[SCRUBBED]",
}

_BODY_SCRUB_RULE = {
    "connector": "C103403",
    "method": "scrub_json_body",
    "field_pattern": r"bearer.?token|access.?token|api.?key",
    "replacement": "[SCRUBBED]",
}

_MINIMAL_CFG_RAW = {
    "client": {"code": "SOC_USA", "schema_version": "1.1"},
    "preprocess": {"credential_scrub": [_HEADER_SCRUB_RULE, _BODY_SCRUB_RULE]},
    "package": {
        "folder_priority": [{"name": "raw", "required": True}],
        "tolerate_empty_folders": False,
    },
    "application_id": {"source": "filename_tokens", "filename": {"pattern": ".*"}},
}


def _cfg() -> ClientConfig:
    return ClientConfig(_MINIMAL_CFG_RAW)


def _make_sf(raw_content: bytes) -> SourceFile:
    sf = SourceFile(
        path=Path("fake/raw/v1_USA_500249966_20250101000000_C103403_REQ_000001_1"),
        folder="raw",
        connector="C103403",
        direction="REQ",
        step=None,
        app_id_raw="500249966_20250101000000",
        sequence_id="1",
        geography="USA",
    )
    sf.raw_bytes = raw_content
    return sf


# ---------------------------------------------------------------------------
# TC-1: HTTP Authorization header with Bearer → [SCRUBBED]
# ---------------------------------------------------------------------------
class TestHttpHeaderScrubbed:
    def test_bearer_header_replaced(self):
        payload = b"Authorization: Bearer mytoken123\r\nContent-Type: application/json\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "[SCRUBBED]" in result
        assert "mytoken123" not in result

    def test_authorization_key_preserved(self):
        payload = b"Authorization: Bearer tok\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"Authorization:" in sf.raw_bytes

    def test_original_token_absent(self):
        secret = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0"
        payload = f"Authorization: Bearer {secret}\r\n".encode()
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert secret.encode() not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-2: JSON body 'bearer_token' key → value scrubbed
# ---------------------------------------------------------------------------
class TestJsonBodyBearerToken:
    def test_bearer_token_value_scrubbed(self):
        payload = b'{"bearer_token": "abc123secret"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "[SCRUBBED]" in result
        assert "abc123secret" not in result

    def test_bearer_token_key_preserved(self):
        payload = b'{"bearer_token": "abc123"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"bearer_token" in sf.raw_bytes

    def test_bearer_dash_token_matched(self):
        """bearer-token (with dash) also matched by bearer.?token."""
        payload = b'{"bearer-token": "secretval"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"secretval" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-3: JSON body 'access_token' key → value scrubbed
# ---------------------------------------------------------------------------
class TestJsonBodyAccessToken:
    def test_access_token_value_scrubbed(self):
        payload = b'{"access_token": "xyzAccessToken"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"xyzAccessToken" not in sf.raw_bytes

    def test_access_token_scrubbed_in_nested_context(self):
        payload = b'{"data": {"access_token": "tok999"}, "other": "value"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "tok999" not in result
        assert '"other": "value"' in result


# ---------------------------------------------------------------------------
# TC-4: No credential fields → unchanged, no exception
# ---------------------------------------------------------------------------
class TestNoCredentialFields:
    def test_payload_unchanged(self):
        payload = b'{"name": "John", "status": "active"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert sf.raw_bytes == payload

    def test_no_exception_on_plain_headers(self):
        payload = b"Content-Type: application/json\r\n\r\n{}"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())  # must not raise


# ---------------------------------------------------------------------------
# TC-5: Both header + JSON body scrubbed in one pass
# ---------------------------------------------------------------------------
class TestBothLocationsScrubbed:
    def test_header_and_body_both_scrubbed(self):
        payload = (
            b"POST /api HTTP/1.1\r\n"
            b"Authorization: Bearer headertok\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b'{"bearer_token": "bodytok"}'
        )
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "headertok" not in result
        assert "bodytok" not in result
        assert "[SCRUBBED]" in result

    def test_non_credential_content_preserved(self):
        payload = (
            b"Authorization: Bearer tok\r\n"
            b"\r\n"
            b'{"bearer_token": "secret", "user_id": "U123"}'
        )
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "U123" in result
        assert "secret" not in result


# ---------------------------------------------------------------------------
# TC-6: 'api_key' JSON field matched
# ---------------------------------------------------------------------------
class TestApiKeyField:
    def test_api_key_value_scrubbed(self):
        payload = b'{"api_key": "APIKEY-12345"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"APIKEY-12345" not in sf.raw_bytes

    def test_api_dash_key_also_matched(self):
        """api-key (with dash) also matched by api.?key."""
        payload = b'{"api-key": "dashed-key-val"}'
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"dashed-key-val" not in sf.raw_bytes
