"""
tests/unit/test_ec_pii_scan.py — TASK-7.2
Unit tests for _scan_extra_columns_for_pii() — INV-02 second enforcement path.

Scans field VALUES (not names) across all rec.extra_columns entries.
PII match → replace with 'TOK_EC_' + sha256(val)[:16].
Lineage: rec.lineage['extra_columns_pii_found'][{key, pattern}].

Patterns used (compiled at module level in engine):
  email, phone, ssn, sin, fein

INV-02: scan must run on EVERY AppRecord; pattern-based on values, not field names.

TC-1: Email value tokenised
TC-2: Phone value tokenised
TC-3: Non-PII value unchanged
TC-4: Field NAME='email' but value has no PII → unchanged (value-scan confirmed)
TC-5: Lineage records pattern and key for each match
TC-6: SSN / SIN values tokenised
TC-7: Nested extra_columns structure scanned recursively
TC-8: Token has 'TOK_EC_' prefix
"""
import hashlib

import pytest

from scripts.ingest_lib import (
    AppRecord,
    _scan_extra_columns_for_pii,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(**ec_groups) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    rec.extra_columns = dict(ec_groups)
    return rec


def _cfg_scan_enabled() -> dict:
    return {
        "pii": {
            "fields": [],
            "extra_columns_scan": {"enabled": True, "patterns": []},
        }
    }


def _tok_ec(val: str) -> str:
    return "TOK_EC_" + hashlib.sha256(val.encode()).hexdigest()[:16]


# ---------------------------------------------------------------------------
# TC-1: Email value → tokenised
# ---------------------------------------------------------------------------
class TestEmailScan:
    def test_email_value_tokenised(self):
        rec = _make_rec(SOC_group={"field": "test@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["field"] == _tok_ec("test@example.com")

    def test_email_raw_value_absent_after_scan(self):
        rec = _make_rec(SOC_group={"contact": "user@domain.org"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert "user@domain.org" not in str(rec.extra_columns)

    def test_email_with_plus_sign_tokenised(self):
        rec = _make_rec(SOC_group={"val": "user+tag@example.co.uk"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["val"].startswith("TOK_EC_")


# ---------------------------------------------------------------------------
# TC-2: Phone value → tokenised
# ---------------------------------------------------------------------------
class TestPhoneScan:
    def test_us_phone_tokenised(self):
        rec = _make_rec(SOC_group={"phone": "555-123-4567"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["phone"].startswith("TOK_EC_")

    def test_raw_phone_absent_after_scan(self):
        rec = _make_rec(SOC_group={"phone": "555-123-4567"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert "555-123-4567" not in str(rec.extra_columns)

    def test_phone_with_country_code_tokenised(self):
        rec = _make_rec(SOC_group={"phone": "+1 (800) 555-1234"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["phone"].startswith("TOK_EC_")


# ---------------------------------------------------------------------------
# TC-3: Non-PII value → unchanged
# ---------------------------------------------------------------------------
class TestNonPiiUnchanged:
    def test_plain_text_not_tokenised(self):
        rec = _make_rec(SOC_group={"description": "no pii here"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["description"] == "no pii here"

    def test_numeric_string_not_tokenised(self):
        rec = _make_rec(SOC_group={"score": "720"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["score"] == "720"

    def test_empty_string_not_tokenised(self):
        rec = _make_rec(SOC_group={"field": ""})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["field"] == ""


# ---------------------------------------------------------------------------
# TC-4: Field NAME='email' but value has no PII → unchanged (value-scan confirmed)
# ---------------------------------------------------------------------------
class TestFieldNameIrrelevant:
    def test_field_named_email_with_safe_value_unchanged(self):
        rec = _make_rec(SOC_group={"email": "not_an_email_at_all"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["email"] == "not_an_email_at_all"

    def test_field_named_ssn_with_safe_value_unchanged(self):
        rec = _make_rec(SOC_group={"ssn": "no ssn pattern here"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["ssn"] == "no ssn pattern here"

    def test_field_with_unexpected_name_but_email_value_tokenised(self):
        """Value is what matters — not the field name."""
        rec = _make_rec(SOC_group={"randomField": "user@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["randomField"].startswith("TOK_EC_")


# ---------------------------------------------------------------------------
# TC-5: Lineage records pattern and key for each match
# ---------------------------------------------------------------------------
class TestLineageRecorded:
    def test_lineage_entry_created_on_match(self):
        rec = _make_rec(SOC_group={"field": "test@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        found = rec.lineage.get("extra_columns_pii_found", [])
        assert len(found) == 1

    def test_lineage_entry_has_key_and_pattern(self):
        rec = _make_rec(SOC_group={"field": "test@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        entry = rec.lineage["extra_columns_pii_found"][0]
        assert "key" in entry
        assert "pattern" in entry
        assert entry["pattern"] == "email"

    def test_no_lineage_when_no_pii(self):
        rec = _make_rec(SOC_group={"field": "safe text"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert "extra_columns_pii_found" not in rec.lineage

    def test_multiple_matches_create_multiple_lineage_entries(self):
        rec = _make_rec(SOC_group={
            "email_field": "a@b.com",
            "phone_field": "555-123-4567",
        })
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        found = rec.lineage.get("extra_columns_pii_found", [])
        assert len(found) == 2


# ---------------------------------------------------------------------------
# TC-6: SSN / SIN tokenised
# ---------------------------------------------------------------------------
class TestSsnSinScan:
    def test_ssn_value_tokenised(self):
        rec = _make_rec(SOC_group={"ssn_val": "123-45-6789"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["ssn_val"].startswith("TOK_EC_")

    def test_sin_value_tokenised(self):
        rec = _make_rec(SOC_group={"sin_val": "123 456 789"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["sin_val"].startswith("TOK_EC_")


# ---------------------------------------------------------------------------
# TC-7: Nested extra_columns structure scanned recursively
# ---------------------------------------------------------------------------
class TestNestedScan:
    def test_nested_dict_value_tokenised(self):
        rec = _make_rec(SOC_group={"sub": {"email": "user@test.com"}})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["sub"]["email"].startswith("TOK_EC_")

    def test_sibling_safe_field_untouched(self):
        rec = _make_rec(SOC_group={"sub": {"email": "user@test.com", "safe": "ok"}})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        assert rec.extra_columns["SOC_group"]["sub"]["safe"] == "ok"


# ---------------------------------------------------------------------------
# TC-8: Token has 'TOK_EC_' prefix + 16 hex chars
# ---------------------------------------------------------------------------
class TestTokenFormat:
    def test_token_starts_with_tok_ec(self):
        rec = _make_rec(SOC_group={"v": "user@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        token = rec.extra_columns["SOC_group"]["v"]
        assert token.startswith("TOK_EC_")

    def test_token_length_correct(self):
        rec = _make_rec(SOC_group={"v": "user@example.com"})
        _scan_extra_columns_for_pii(rec, _cfg_scan_enabled())
        token = rec.extra_columns["SOC_group"]["v"]
        # 'TOK_EC_' (7) + 16 hex chars = 23
        assert len(token) == 23

    def test_token_deterministic(self):
        rec1 = _make_rec(SOC_group={"v": "user@example.com"})
        rec2 = _make_rec(SOC_group={"v": "user@example.com"})
        _scan_extra_columns_for_pii(rec1, _cfg_scan_enabled())
        _scan_extra_columns_for_pii(rec2, _cfg_scan_enabled())
        assert (
            rec1.extra_columns["SOC_group"]["v"]
            == rec2.extra_columns["SOC_group"]["v"]
        )
