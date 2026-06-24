"""
tests/unit/test_scrub_c754889.py — TASK-2.2
Unit tests for credential scrub: connector C754889 (plain-text password fields).

Invariant verified:
  INV-01 (pattern-based): scrub matches field names by pattern, not by
    known credential value. A new password format is still caught.
  INV-01 (scrub first): sf.raw_bytes overwritten in-place; no original
    credential value remains accessible downstream.

TC-1: 'password=abc123' → value nulled (field name + '=' preserved, value empty)
TC-2: 'Password=ABC' → case-insensitive match, value nulled
TC-3: 'username=admin&pwd=secret' → pwd value nulled; username value preserved
TC-4: No credential fields present → payload unchanged, no exception raised
TC-5: 'passwd=x&pass=y' → both nulled by pattern
TC-6: sf.raw_bytes after scrub contains no original credential value
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import ClientConfig, SourceFile, scrub_credentials


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
_SCRUB_RULE = {
    "connector": "C754889",
    "method": "null_out",
    "field_pattern": r"password|passwd|pwd|pass",
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
    sf = SourceFile(
        path=Path("fake/raw/v1_USA_500249966_20250101000000_C754889_REQ_000001_1"),
        folder="raw",
        connector="C754889",
        direction="REQ",
        step=None,
        app_id_raw="500249966_20250101000000",
        sequence_id="1",
        geography="USA",
    )
    sf.raw_bytes = raw_content
    return sf


# ---------------------------------------------------------------------------
# TC-1: password field value nulled
# ---------------------------------------------------------------------------
class TestPasswordNulled:
    def test_password_value_removed(self):
        sf = _make_sf(b"password=abc123")
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert result == "password=", f"Expected 'password=', got {result!r}"

    def test_password_key_preserved(self):
        sf = _make_sf(b"password=abc123")
        scrub_credentials([sf], _cfg())
        assert b"password=" in sf.raw_bytes

    def test_original_value_absent(self):
        sf = _make_sf(b"password=abc123")
        scrub_credentials([sf], _cfg())
        assert b"abc123" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-2: Case-insensitive match ('Password=ABC')
# ---------------------------------------------------------------------------
class TestCaseInsensitive:
    def test_uppercase_password_matched(self):
        sf = _make_sf(b"Password=ABC")
        scrub_credentials([sf], _cfg())
        assert b"ABC" not in sf.raw_bytes

    def test_mixed_case_password_matched(self):
        sf = _make_sf(b"PASSWORD=secret")
        scrub_credentials([sf], _cfg())
        assert b"secret" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-3: Multi-field form: username preserved, pwd nulled
# ---------------------------------------------------------------------------
class TestMultiFieldForm:
    def test_pwd_nulled_username_preserved(self):
        sf = _make_sf(b"username=admin&pwd=secret")
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "username=admin" in result, "username value must be preserved"
        assert "pwd=" in result, "pwd key must be preserved"
        assert "secret" not in result, "pwd value must be nulled"

    def test_form_structure_intact(self):
        sf = _make_sf(b"username=admin&pwd=secret&token=xyz")
        scrub_credentials([sf], _cfg())
        result = sf.raw_bytes.decode("utf-8")
        assert "username=admin" in result
        assert "token=xyz" in result
        assert "secret" not in result


# ---------------------------------------------------------------------------
# TC-4: No credential fields → unchanged, no exception
# ---------------------------------------------------------------------------
class TestNoCredentialFields:
    def test_payload_unchanged(self):
        payload = b"username=admin&email=a@b.com"
        sf = _make_sf(payload)
        scrub_credentials([sf], _cfg())
        assert sf.raw_bytes == payload

    def test_no_exception_raised(self):
        sf = _make_sf(b"key=value&other=123")
        scrub_credentials([sf], _cfg())  # must not raise


# ---------------------------------------------------------------------------
# TC-5: passwd and pass also matched by pattern
# ---------------------------------------------------------------------------
class TestAliasPatterns:
    def test_passwd_nulled(self):
        sf = _make_sf(b"passwd=hunter2")
        scrub_credentials([sf], _cfg())
        assert b"hunter2" not in sf.raw_bytes

    def test_pass_nulled(self):
        sf = _make_sf(b"pass=p@ssw0rd")
        scrub_credentials([sf], _cfg())
        assert b"p@ssw0rd" not in sf.raw_bytes

    def test_both_passwd_and_pass_nulled(self):
        sf = _make_sf(b"passwd=aaa&pass=bbb")
        scrub_credentials([sf], _cfg())
        assert b"aaa" not in sf.raw_bytes
        assert b"bbb" not in sf.raw_bytes


# ---------------------------------------------------------------------------
# TC-6: sf.raw_bytes overwritten in-place after scrub
# ---------------------------------------------------------------------------
class TestRawBytesOverwritten:
    def test_raw_bytes_overwritten(self):
        sf = _make_sf(b"password=supersecret")
        scrub_credentials([sf], _cfg())
        assert b"supersecret" not in sf.raw_bytes

    def test_raw_bytes_is_bytes_type(self):
        sf = _make_sf(b"password=val")
        scrub_credentials([sf], _cfg())
        assert isinstance(sf.raw_bytes, bytes)
