"""
tests/unit/test_tokenise.py — TASK-7.1
Unit tests for tokenise_pii() static PII field tokenisation.

Methods:
  pseudonym_reversible: 'TOK_' + sha256(value)[:16]  (vault stub)
  oneway_hash:          sha256(value).hexdigest()
  year_only:            first 4-digit year component extracted
  scrub_never_store:    field removed entirely from rec.record

INV-02 / D-07: tokenise_pii() must complete before write_record().
After completion, no field in pii.fields retains its raw value.

TC-1: pseudonym_reversible — firstName → 'TOK_' + hash
TC-2: oneway_hash — SSN → SHA-256 hex
TC-3: year_only — DOB → year string only
TC-4: scrub_never_store — field removed from rec.record
TC-5: All fields tokenised → raw values absent from rec.record
TC-6: Field absent in rec.record → no error (graceful null)
"""
import hashlib

import pytest

from scripts.ingest_lib import (
    AppRecord,
    _del_path,
    _get_path,
    _set_path,
    _tokenise_value,
    tokenise_pii,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(**record_kwargs) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    for path, val in record_kwargs.items():
        _set_path(rec.record, path.replace("__", "."), val)
    return rec


def _cfg(*pii_fields) -> dict:
    return {
        "pii": {
            "fields": list(pii_fields),
            "extra_columns_scan": {"enabled": False, "patterns": []},
        },
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# ---------------------------------------------------------------------------
# TC-1: pseudonym_reversible — firstName → 'TOK_' + hash[:16]
# ---------------------------------------------------------------------------
class TestPseudonymReversible:
    def test_firstname_tokenised_with_tok_prefix(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "John")
        cfg = _cfg({"path": "applicant.firstName", "method": "pseudonym_reversible"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.firstName")
        assert result.startswith("TOK_")

    def test_firstname_token_length(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "John")
        cfg = _cfg({"path": "applicant.firstName", "method": "pseudonym_reversible"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.firstName")
        # 'TOK_' (4) + 16 hex chars = 20
        assert len(result) == 20

    def test_firstname_token_deterministic(self):
        """Same input always produces same token (deterministic hash)."""
        rec1 = _make_rec()
        rec2 = _make_rec()
        _set_path(rec1.record, "applicant.firstName", "Alice")
        _set_path(rec2.record, "applicant.firstName", "Alice")
        cfg = _cfg({"path": "applicant.firstName", "method": "pseudonym_reversible"})
        tokenise_pii(rec1, cfg)
        tokenise_pii(rec2, cfg)
        assert (
            _get_path(rec1.record, "applicant.firstName")
            == _get_path(rec2.record, "applicant.firstName")
        )

    def test_raw_firstname_absent_after_tokenise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "John")
        cfg = _cfg({"path": "applicant.firstName", "method": "pseudonym_reversible"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.firstName")
        assert result != "John"


# ---------------------------------------------------------------------------
# TC-2: oneway_hash — SSN → SHA-256 hex
# ---------------------------------------------------------------------------
class TestOneWayHash:
    def test_ssn_becomes_sha256_hex(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        cfg = _cfg({"path": "applicant.ssn", "method": "oneway_hash"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.ssn")
        assert result == _sha256("123-45-6789")

    def test_ssn_hash_is_64_hex_chars(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "987-65-4321")
        cfg = _cfg({"path": "applicant.ssn", "method": "oneway_hash"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.ssn")
        assert len(result) == 64
        assert all(c in "0123456789abcdef" for c in result)

    def test_raw_ssn_absent_after_hash(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "111-22-3333")
        cfg = _cfg({"path": "applicant.ssn", "method": "oneway_hash"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.ssn")
        assert result != "111-22-3333"


# ---------------------------------------------------------------------------
# TC-3: year_only — DOB → year string only
# ---------------------------------------------------------------------------
class TestYearOnly:
    def test_iso_date_truncated_to_year(self):
        result = _tokenise_value("1990-05-15", "year_only")
        assert result == "1990"

    def test_slash_date_truncated_to_year(self):
        result = _tokenise_value("05/15/1990", "year_only")
        assert result == "1990"

    def test_dob_tokenised_via_tokenise_pii(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.dateOfBirth", "1985-03-22")
        cfg = _cfg({"path": "applicant.dateOfBirth", "method": "year_only"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.dateOfBirth")
        assert result == "1985"

    def test_full_date_absent_after_year_only(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.dateOfBirth", "1985-03-22")
        cfg = _cfg({"path": "applicant.dateOfBirth", "method": "year_only"})
        tokenise_pii(rec, cfg)
        result = _get_path(rec.record, "applicant.dateOfBirth")
        assert result != "1985-03-22"


# ---------------------------------------------------------------------------
# TC-4: scrub_never_store — field removed from rec.record
# ---------------------------------------------------------------------------
class TestScrubNeverStore:
    def test_field_removed_from_record(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.sin", "123 456 789")
        cfg = _cfg({"path": "applicant.sin", "method": "scrub_never_store"})
        tokenise_pii(rec, cfg)
        assert _get_path(rec.record, "applicant.sin") is None

    def test_sibling_fields_not_removed(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.sin", "123 456 789")
        _set_path(rec.record, "applicant.firstName", "Jane")
        cfg = _cfg({"path": "applicant.sin", "method": "scrub_never_store"})
        tokenise_pii(rec, cfg)
        # firstName must survive; only sin removed
        assert _get_path(rec.record, "applicant.firstName") == "Jane"

    def test_del_path_helper_removes_leaf(self):
        obj = {"a": {"b": {"c": "secret"}}}
        _del_path(obj, "a.b.c")
        assert obj == {"a": {"b": {}}}

    def test_del_path_missing_key_no_error(self):
        obj = {"a": {"b": {}}}
        _del_path(obj, "a.b.nonexistent")   # must not raise


# ---------------------------------------------------------------------------
# TC-5: Multiple fields — all raw values absent after tokenise_pii
# ---------------------------------------------------------------------------
class TestAllFieldsTokenised:
    def test_all_raw_values_replaced(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "John")
        _set_path(rec.record, "applicant.lastName", "Doe")
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        _set_path(rec.record, "applicant.dateOfBirth", "1980-01-01")
        cfg = _cfg(
            {"path": "applicant.firstName", "method": "pseudonym_reversible"},
            {"path": "applicant.lastName", "method": "pseudonym_reversible"},
            {"path": "applicant.ssn", "method": "oneway_hash"},
            {"path": "applicant.dateOfBirth", "method": "year_only"},
        )
        tokenise_pii(rec, cfg)
        import json
        blob = json.dumps(rec.record)
        assert "John" not in blob
        assert "Doe" not in blob
        assert "123-45-6789" not in blob
        assert "1980-01-01" not in blob

    def test_tokens_present_after_all_tokenised(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "Alice")
        cfg = _cfg({"path": "applicant.firstName", "method": "pseudonym_reversible"})
        tokenise_pii(rec, cfg)
        token = _get_path(rec.record, "applicant.firstName")
        assert token is not None
        assert token.startswith("TOK_")


# ---------------------------------------------------------------------------
# TC-6: Field absent in rec.record → no error
# ---------------------------------------------------------------------------
class TestGracefulNull:
    def test_absent_field_no_error(self):
        rec = _make_rec()   # no PII fields set
        cfg = _cfg(
            {"path": "applicant.ssn", "method": "oneway_hash"},
            {"path": "applicant.sin", "method": "scrub_never_store"},
        )
        tokenise_pii(rec, cfg)   # must not raise

    def test_absent_field_no_change_to_record(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "Bob")
        cfg = _cfg(
            {"path": "applicant.ssn", "method": "oneway_hash"},   # ssn absent
        )
        tokenise_pii(rec, cfg)
        # firstName untouched since it's not in pii.fields
        assert _get_path(rec.record, "applicant.firstName") == "Bob"
