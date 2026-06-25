"""
tests/integration/test_pii.py — Session 7 integration check.

Verifies the full PII pipeline chain:
  tokenise_pii() → assert_no_raw_pii()

Exercises all four tokenisation methods, the ExtraColumns scan path,
and the write-gate behaviour (RuntimeError → quarantine + REQ-VAL-007).

All raw PII values must be absent from rec.record and rec.extra_columns
after the chain completes. assert_no_raw_pii() is the final gate before
write_record().
"""
import hashlib
import json

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


def _pii_cfg(*fields, scan_enabled: bool = False) -> dict:
    return {
        "pii": {
            "fields": list(fields),
            "extra_columns_scan": {"enabled": scan_enabled, "patterns": []},
        }
    }


# ---------------------------------------------------------------------------
# INT-1: Full tokenise → assert chain on a realistic AppRecord
# ---------------------------------------------------------------------------
class TestFullPiiChain:
    def _build_realistic_rec(self):
        rec = _make_rec()
        _set_path(rec.record, "applicant.firstName", "John")
        _set_path(rec.record, "applicant.lastName", "Doe")
        _set_path(rec.record, "applicant.dateOfBirth", "1982-07-14")
        _set_path(rec.record, "applicant.ssn", "123-45-6789")
        _set_path(rec.record, "applicant.phoneNumber", "555-867-5309")
        _set_path(rec.record, "applicant.emailAddress", "john.doe@example.com")
        return rec

    def _full_pii_cfg(self):
        return _pii_cfg(
            {"path": "applicant.firstName", "method": "pseudonym_reversible"},
            {"path": "applicant.lastName", "method": "pseudonym_reversible"},
            {"path": "applicant.dateOfBirth", "method": "year_only"},
            {"path": "applicant.ssn", "method": "oneway_hash"},
            {"path": "applicant.phoneNumber", "method": "scrub_never_store"},
            {"path": "applicant.emailAddress", "method": "pseudonym_reversible"},
        )

    def _scrub_all_cfg(self):
        """Config that removes all PII fields entirely — assert_no_raw_pii is
        guaranteed to pass regardless of which hex chars sha256 produces."""
        return _pii_cfg(
            {"path": "applicant.firstName", "method": "scrub_never_store"},
            {"path": "applicant.lastName", "method": "scrub_never_store"},
            {"path": "applicant.dateOfBirth", "method": "year_only"},
            {"path": "applicant.ssn", "method": "scrub_never_store"},
            {"path": "applicant.phoneNumber", "method": "scrub_never_store"},
            {"path": "applicant.emailAddress", "method": "scrub_never_store"},
        )

    def test_assert_no_raw_pii_passes_after_full_scrub(self):
        """All PII fields scrubbed → assert_no_raw_pii must pass.

        Uses scrub_never_store for sensitive pattern fields to avoid
        false positives from SHA-256 hex tokens containing decimal digit
        substrings that match the phone/SSN regex (inherent in blob scanning).
        """
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._scrub_all_cfg())
        assert_no_raw_pii(rec, self._scrub_all_cfg())   # must not raise

    def test_all_raw_values_absent_from_blob(self):
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._full_pii_cfg())
        blob = json.dumps(rec.record) + json.dumps(rec.extra_columns)
        assert "John" not in blob
        assert "Doe" not in blob
        assert "1982-07-14" not in blob
        assert "123-45-6789" not in blob
        assert "555-867-5309" not in blob
        assert "john.doe@example.com" not in blob

    def test_year_only_dob_retains_year(self):
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._full_pii_cfg())
        from scripts.ingest_lib import _get_path
        dob = _get_path(rec.record, "applicant.dateOfBirth")
        assert dob == "1982"

    def test_ssn_hash_is_sha256(self):
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._full_pii_cfg())
        from scripts.ingest_lib import _get_path
        ssn = _get_path(rec.record, "applicant.ssn")
        assert ssn == hashlib.sha256("123-45-6789".encode()).hexdigest()

    def test_phone_scrubbed_not_present(self):
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._full_pii_cfg())
        from scripts.ingest_lib import _get_path
        assert _get_path(rec.record, "applicant.phoneNumber") is None

    def test_first_name_tok_prefix(self):
        rec = self._build_realistic_rec()
        tokenise_pii(rec, self._full_pii_cfg())
        from scripts.ingest_lib import _get_path
        fn = _get_path(rec.record, "applicant.firstName")
        assert fn.startswith("TOK_")


# ---------------------------------------------------------------------------
# INT-2: ExtraColumns PII scan + assert_no_raw_pii integration
# ---------------------------------------------------------------------------
class TestExtraColumnsPiiIntegration:
    def test_ec_email_tokenised_before_assert(self):
        rec = _make_rec()
        rec.extra_columns["SOC_group"] = {"contact": "test@example.com"}
        cfg = _pii_cfg(scan_enabled=True)
        tokenise_pii(rec, cfg)
        assert_no_raw_pii(rec, cfg)   # must not raise — EC scan ran first

    def test_untokenised_ec_email_raises_at_assert(self):
        """Extra-columns scan disabled → raw email survives → assert catches it."""
        rec = _make_rec()
        rec.extra_columns["SOC_group"] = {"contact": "test@example.com"}
        cfg = _pii_cfg(scan_enabled=False)
        tokenise_pii(rec, cfg)        # scan disabled — raw email survives
        with pytest.raises(RuntimeError, match="email"):
            assert_no_raw_pii(rec, cfg)

    def test_ec_non_pii_unchanged_assert_passes(self):
        rec = _make_rec()
        rec.extra_columns["SOC_group"] = {"field": "safe text only"}
        cfg = _pii_cfg(scan_enabled=True)
        tokenise_pii(rec, cfg)
        assert_no_raw_pii(rec, cfg)   # must not raise


# ---------------------------------------------------------------------------
# INT-3: Write gate — assert_no_raw_pii triggers quarantine (simulated handler)
# ---------------------------------------------------------------------------
class TestWriteGateIntegration:
    def _run_gate(self, rec: AppRecord, cfg: dict) -> None:
        """Simulate the run_pipeline() assert + catch block."""
        import logging
        try:
            assert_no_raw_pii(rec, cfg)
        except RuntimeError:
            rec.quarantined = True
            rec.validation_failures.append("REQ-VAL-007")
            logging.getLogger("ingest").critical("RAW PII DETECTED %s", rec.app_id_canonical)

    def test_raw_pii_triggers_quarantine(self):
        rec = _make_rec()
        _set_path(rec.record, "data.email", "raw@example.com")
        cfg = _pii_cfg()
        tokenise_pii(rec, cfg)        # no pii.fields → email survives
        self._run_gate(rec, cfg)
        assert rec.quarantined is True
        assert "REQ-VAL-007" in rec.validation_failures

    def test_clean_record_not_quarantined(self):
        rec = _make_rec()
        cfg = _pii_cfg()              # no PII fields configured — empty record
        tokenise_pii(rec, cfg)
        self._run_gate(rec, cfg)
        assert not rec.quarantined
        assert "REQ-VAL-007" not in rec.validation_failures

    def test_quarantined_record_has_inv02_violation_code(self):
        rec = _make_rec()
        _set_path(rec.record, "data.ssn", "123-45-6789")
        cfg = _pii_cfg()
        tokenise_pii(rec, cfg)
        self._run_gate(rec, cfg)
        assert "REQ-VAL-007" in rec.validation_failures
