"""
tests/unit/test_scrub_c161653.py — TASK-2.1
Unit tests for credential scrub: connector C161653 (OAuth Authorization header).

Invariant verified:
  INV-01 (pattern-based): scrub uses regex, not exact known-token matching.
  INV-01 (scrub first): sf.raw_bytes is overwritten in-place; no original token
    remains accessible to downstream functions after scrub.

TC-1: 'Authorization: Bearer abc123' → header value redacted to [REDACTED]
TC-2: 'Authorization: Basic dXNlcjpwYXNz' → header value redacted to [REDACTED]
TC-3: No Authorization header present → payload unchanged, no exception raised
TC-4: sf.raw_bytes after scrub contains no original token string
TC-5: Scrub is case-insensitive ('authorization:' lowercase also matched)
TC-6: Token surrounded by other headers is still redacted; other headers intact
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.ingest_lib import ClientConfig, SourceFile, scrub_credentials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_SCRUB_RULE = {
    "connector": "C161653",
    "method": "redact",
    # IC-4: pattern must match full credential value to end-of-line.
    # EXECUTION_PLAN specified \S+ which only matches the scheme word; corrected
    # to [^\r\n]+ so the token value itself is also redacted.
    "pattern": r"(?i)(Authorization:\s*)[^\r\n]+",
    "replacement": r"\1[REDACTED]",
}

_MINIMAL_CFG_RAW = {
    "client": {"code": "SOC_USA", "schema_version": "1.1"},
    "preprocess": {"credential_scrub": [_SCRUB_RULE]},
    "package": {
        "folder_priority": [{"name": "raw", "required": True}],
        "tolerate_empty_folders": False,
    },
    "application_id": {"source": "filename_tokens", "filename": {"pattern": ".*"}},
}


def _cfg() -> ClientConfig:
    return ClientConfig(_MINIMAL_CFG_RAW)


def _make_sf(raw_content: bytes) -> SourceFile:
    """Build a SourceFile with raw_bytes pre-loaded (no disk I/O needed)."""
    sf = SourceFile(
        path=Path("fake/raw/v1_USA_500249966_20250101000000_C161653_REQ_000001_1"),
        folder="raw",
        connector="C161653",
        direction="REQ",
        step=None,
        app_id_raw="500249966_20250101000000",
        sequence_id="1",
        geography="USA",
    )
    sf.raw_bytes = raw_content
    return sf


# ---------------------------------------------------------------------------
# TC-1: Bearer token redacted
# ---------------------------------------------------------------------------
class TestBearerTokenRedacted:
    def test_bearer_value_replaced(self):
        payload = b"Authorization: Bearer abc123\r\nContent-Type: application/json\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "[REDACTED]" in result, "Expected [REDACTED] in scrubbed payload"

    def test_original_token_absent(self):
        payload = b"Authorization: Bearer abc123\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"abc123" not in sf.raw_bytes, "Original Bearer token must not remain in raw_bytes"

    def test_authorization_key_preserved(self):
        payload = b"Authorization: Bearer abc123\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "Authorization:" in result, "Authorization header name must be preserved"


# ---------------------------------------------------------------------------
# TC-2: Basic auth token redacted
# ---------------------------------------------------------------------------
class TestBasicAuthRedacted:
    def test_basic_value_replaced(self):
        payload = b"Authorization: Basic dXNlcjpwYXNz\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "[REDACTED]" in result

    def test_original_basic_token_absent(self):
        payload = b"Authorization: Basic dXNlcjpwYXNz\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"dXNlcjpwYXNz" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-3: No Authorization header → unchanged, no exception
# ---------------------------------------------------------------------------
class TestNoAuthorizationHeader:
    def test_payload_unchanged_when_no_auth_header(self):
        payload = b"Content-Type: application/json\r\nX-Custom: value\r\n\r\n{}"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert sf.raw_bytes == payload, "Payload must be unchanged when no Authorization header"

    def test_no_exception_raised(self):
        payload = b"Content-Type: text/plain\r\n\r\nsome body"
        sf = _make_sf(payload)
        # Must not raise
        scrub_credentials([sf], _cfg())


# ---------------------------------------------------------------------------
# TC-4: sf.raw_bytes after scrub contains no original token
# ---------------------------------------------------------------------------
class TestRawBytesOverwritten:
    def test_raw_bytes_overwritten_in_place(self):
        token = "eyJhbGciOiJSUzI1NiJ9.eyJzdWIiOiJ1c2VyIn0.signature"
        payload = f"Authorization: Bearer {token}\r\n".encode("utf-8")
        sf = _make_sf(payload)
        original_id = id(sf)
        scrub_credentials([sf], _cfg())
        assert token.encode("utf-8") not in sf.raw_bytes, (
            "Token must not remain in sf.raw_bytes after scrub"
        )

    def test_raw_bytes_is_bytes_after_scrub(self):
        payload = b"Authorization: Bearer tok123\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert isinstance(sf.raw_bytes, bytes)


# ---------------------------------------------------------------------------
# TC-5: Case-insensitive match
# ---------------------------------------------------------------------------
class TestCaseInsensitiveMatch:
    def test_lowercase_authorization_matched(self):
        payload = b"authorization: Bearer secret\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"secret" not in sf.raw_bytes

    def test_mixed_case_authorization_matched(self):
        payload = b"AUTHORIZATION: Bearer secret2\r\n"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert b"secret2" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-6: Other headers preserved after scrub
# ---------------------------------------------------------------------------
class TestOtherHeadersPreserved:
    def test_other_headers_intact(self):
        payload = (
            b"POST /api HTTP/1.1\r\n"
            b"Host: example.com\r\n"
            b"Authorization: Bearer mytoken\r\n"
            b"Content-Type: application/json\r\n"
            b"\r\n"
            b"{\"key\": \"value\"}"
        )
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "Host: example.com" in result
        assert "Content-Type: application/json" in result
        assert "mytoken" not in result
        assert "[REDACTED]" in result
