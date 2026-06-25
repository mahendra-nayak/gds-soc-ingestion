"""
tests/unit/test_zero_pii.py — TASK-7.3
Unit tests for assert_no_raw_pii() — write gate (INV-02 / D-07).

assert_no_raw_pii() scans json.dumps(rec.record) + json.dumps(rec.extra_columns)
against _PII_PATTERNS. On match: raises RuntimeError with pattern name, AppID,
and a context snippet. This is a write gate — not a log step.

In run_pipeline():
  except RuntimeError → rec.quarantined=True, REQ-VAL-007 appended, log.critical
  (does NOT re-raise — pipeline continues to next record)

TC-1: All PII tokenised → assert_no_raw_pii passes (no RuntimeError)
TC-2: Raw email injected post-tokenisation → RuntimeError raised
TC-3: RuntimeError message contains pattern name and AppID
TC-4: RuntimeError handler: REQ-VAL-007 in validation_failures
TC-5: RuntimeError handler: record quarantined
TC-6: Multiple patterns — each triggers RuntimeError independently
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    _set_path,
    assert_no_raw_pii,
    tokenise_pii,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(app_id: str = "500249960_20250101000000") -> AppRecord:
    return AppRecord(
        app_id_canonical=app_id,
        app_id_raw=app_id,
        geography="USA",
    )


def _cfg_no_pii() -> dict:
    return {
        "pii": {
            "fields": [],
            "extra_columns_scan": {"enabled": False, "patterns": []},
        }
    }


def _cfg_with_pii(*fields) -> dict:
    return {
        "pii": {
            "fields": list(fields),
            "extra_columns_scan": {"enabled": False, "patterns": []},
        }
    }


# ---------------------------------------------------------------------------
# TC-1: All PII tokenised → assert_no_raw_pii passes
# ---------------------------------------------------------------------------
class TestCleanRecordPasses:
    def test_empty_record_no_raise(self):
        rec = _make_rec()
        assert_no_raw_pii(rec, _cfg_no_pii())   # must not raise

    def test_tokenised_ssn_no_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        tokenise_pii(rec, _cfg_with_pii({"path": "applicant.ssn", "method": "oneway_hash"}))
        assert_no_raw_pii(rec, _cfg_no_pii())   # must not raise

    def test_tokenised_email_no_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.email", "user@example.com")
        tokenise_pii(rec, _cfg_with_pii(
            {"path": "applicant.email", "method": "pseudonym_reversible"}
        ))
        assert_no_raw_pii(rec, _cfg_no_pii())   # must not raise after tokenise

    def test_year_only_dob_no_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.dateOfBirth", "1980-06-15")
        tokenise_pii(rec, _cfg_with_pii(
            {"path": "applicant.dateOfBirth", "method": "year_only"}
        ))
        assert_no_raw_pii(rec, _cfg_no_pii())   # year alone must not trigger

    def test_scrubbed_field_no_raise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.sin", "123 456 789")
        tokenise_pii(rec, _cfg_with_pii(
            {"path": "applicant.sin", "method": "scrub_never_store"}
        ))
        assert_no_raw_pii(rec, _cfg_no_pii())   # field removed → no pattern match


# ---------------------------------------------------------------------------
# TC-2: Raw email injected post-tokenisation → RuntimeError raised
# ---------------------------------------------------------------------------
class TestRawPiiRaisesRuntimeError:
    def test_raw_email_raises(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.email", "raw@example.com")
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_raw_phone_raises(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.phone", "555-123-4567")
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_raw_ssn_raises(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_raw_pii_in_extra_columns_raises(self):
        rec = _make_rec()
        rec.extra_columns["SOC_group"] = {"contact": "user@example.com"}
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())


# ---------------------------------------------------------------------------
# TC-3: RuntimeError message contains pattern name and AppID
# ---------------------------------------------------------------------------
class TestErrorMessageContent:
    def test_error_contains_pattern_name(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.email", "user@example.com")
        with pytest.raises(RuntimeError, match="email"):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_error_contains_app_id(self):
        rec = _make_rec(app_id="APP123_20250101000000")
        _set_path(rec.record, "applicant.email", "user@example.com")
        with pytest.raises(RuntimeError, match="APP123_20250101000000"):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_error_contains_inv02_reference(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.phone", "555-123-4567")
        with pytest.raises(RuntimeError, match="INV-02"):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_error_contains_context_snippet(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.phone", "555-123-4567")
        with pytest.raises(RuntimeError, match="Context:"):
            assert_no_raw_pii(rec, _cfg_no_pii())


# ---------------------------------------------------------------------------
# TC-4 + TC-5: RuntimeError handler (simulated — tests the handler logic directly)
# ---------------------------------------------------------------------------
class TestRuntimeErrorHandler:
    def _apply_handler(self, rec: AppRecord) -> None:
        """Simulate the run_pipeline() try/except block."""
        import logging
        try:
            assert_no_raw_pii(rec, _cfg_no_pii())
        except RuntimeError:
            rec.quarantined = True
            rec.validation_failures.append("REQ-VAL-007")
            logging.getLogger("ingest").critical("RAW PII DETECTED %s", rec.app_id_canonical)

    def test_handler_appends_req_val_007(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.email", "raw@example.com")
        self._apply_handler(rec)
        assert "REQ-VAL-007" in rec.validation_failures

    def test_handler_quarantines_record(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.email", "raw@example.com")
        self._apply_handler(rec)
        assert rec.quarantined is True

    def test_handler_does_not_reraise(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        # must not raise after handler
        self._apply_handler(rec)

    def test_clean_record_handler_no_quarantine(self):
        rec = _make_rec()
        # no PII in record
        self._apply_handler(rec)
        assert not rec.quarantined
        assert "REQ-VAL-007" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-6: Multiple patterns — each triggers independently
# ---------------------------------------------------------------------------
class TestMultiplePatterns:
    def test_ssn_pattern_triggers(self):
        rec = _make_rec()
        _set_path(rec.record, "data.ssn", "123-45-6789")
        with pytest.raises(RuntimeError, match="ssn"):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_sin_pattern_triggers(self):
        rec = _make_rec()
        _set_path(rec.record, "data.sin", "123 456 789")
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())

    def test_fein_pattern_triggers(self):
        rec = _make_rec()
        _set_path(rec.record, "data.fein", "12-3456789")
        with pytest.raises(RuntimeError):
            assert_no_raw_pii(rec, _cfg_no_pii())
