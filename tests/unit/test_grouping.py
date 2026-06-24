"""
tests/unit/test_grouping.py — TASK-3.2
Unit tests for group_by_app(): composite dedup key and D-02 debtor consistency.

Invariants verified:
  D-02: all files in a group must share the same EcsDebtorNumber (debtor_number
    component of app_id_raw). Cross-debtor mismatch → AppRecord quarantined.
  INV-07: sequence_id compared as string only in dedup key — no numeric cast.

TC-1: 5 USA + 3 CAN distinct App IDs → 8 AppRecord objects
TC-2: USA retry — two files same App ID + (connector, direction, sequence_id) → 1 SourceFile retained (latest filename)
TC-3: Cross-debtor mismatch → AppRecord quarantined with D-02 failure
TC-4: Empty file list → empty dict returned
TC-5: Files with app_id_raw=None skipped (unclassified)
TC-6: Two files, same App ID but different sequence → both retained (not deduped)
"""
from pathlib import Path

import pytest

from scripts.ingest_lib import ClientConfig, SourceFile, group_by_app


# ---------------------------------------------------------------------------
# Config stub
# ---------------------------------------------------------------------------
def _cfg() -> ClientConfig:
    return ClientConfig({
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "application_id": {
            "source": "filename_tokens",
            "filename": {"pattern": ".*", "canonical_app_id_groups": ["debtor", "dt"]},
            "suffix_rules": [{"suffix": "_test", "action": "strip", "flag_lineage": True}],
        },
        "sessions": {"model": "single"},
    })


def _make_sf(
    app_id_raw: str | None,
    connector: str = "C225334",
    direction: str = "REQ",
    sequence_id: str = "1",
    filename: str | None = None,
    geography: str = "USA",
) -> SourceFile:
    name = filename or f"v1_{geography}_{app_id_raw or 'unclassified'}_{connector}_{sequence_id}.txt"
    return SourceFile(
        path=Path(f"fake/raw/{name}"),
        folder="raw",
        connector=connector,
        direction=direction,
        step=None,
        app_id_raw=app_id_raw,
        sequence_id=sequence_id,
        geography=geography,
    )


# ---------------------------------------------------------------------------
# TC-1: 5 USA + 3 CAN distinct App IDs → 8 AppRecord objects
# ---------------------------------------------------------------------------
class TestDistinctGroupCount:
    def test_eight_distinct_app_ids_produce_eight_records(self):
        files = (
            [_make_sf(f"50024996{i}_20250101000000", geography="USA") for i in range(5)]
            + [_make_sf(f"60024996{i}_20250101000000", geography="CAN") for i in range(3)]
        )
        apps = group_by_app(files, _cfg())
        assert len(apps) == 8, f"Expected 8 AppRecords, got {len(apps)}"

    def test_all_keys_are_strings(self):
        """INV-07: AppRecord dict keys must be VARCHAR strings."""
        files = [_make_sf(f"50024996{i}_20250101000000") for i in range(3)]
        apps = group_by_app(files, _cfg())
        for key in apps:
            assert isinstance(key, str), f"Key {key!r} must be str"

    def test_files_assigned_to_correct_record(self):
        sf_a = _make_sf("500249960_20250101000000")
        sf_b = _make_sf("500249961_20250101000000")
        apps = group_by_app([sf_a, sf_b], _cfg())
        assert sf_a in apps["500249960_20250101000000"].files
        assert sf_b in apps["500249961_20250101000000"].files


# ---------------------------------------------------------------------------
# TC-2: USA retry deduplication — same (connector, direction, sequence_id) → 1 file kept (latest)
# ---------------------------------------------------------------------------
class TestRetryDeduplication:
    def test_two_files_same_dedup_key_yields_one(self):
        """Latest by filename (alphabetically last) must be retained."""
        sf_old = _make_sf("500249966_20250101000000", connector="C225334",
                          direction="REQ", sequence_id="80",
                          filename="v1_USA_500249966_20250101000000_C225334_REQ_220101110000_80.json")
        sf_new = _make_sf("500249966_20250101000000", connector="C225334",
                          direction="REQ", sequence_id="80",
                          filename="v1_USA_500249966_20250101000000_C225334_REQ_220101120000_80.json")
        apps = group_by_app([sf_old, sf_new], _cfg())
        rec = apps["500249966_20250101000000"]
        assert len(rec.files) == 1, f"Expected 1 file after dedup, got {len(rec.files)}"

    def test_latest_filename_retained_not_oldest(self):
        sf_old = _make_sf("500249966_20250101000000", connector="C225334",
                          direction="REQ", sequence_id="80",
                          filename="v1_USA_500249966_20250101000000_C225334_REQ_220101110000_80.json")
        sf_new = _make_sf("500249966_20250101000000", connector="C225334",
                          direction="REQ", sequence_id="80",
                          filename="v1_USA_500249966_20250101000000_C225334_REQ_220101120000_80.json")
        apps = group_by_app([sf_old, sf_new], _cfg())
        rec = apps["500249966_20250101000000"]
        retained = rec.files[0]
        assert "110000" not in retained.path.name, "Old file must not be retained"
        assert "120000" in retained.path.name, "New file (120000) must be retained"

    def test_non_duplicate_files_both_retained(self):
        """Files with different sequence_id are not duplicates."""
        sf_a = _make_sf("500249966_20250101000000", sequence_id="1")
        sf_b = _make_sf("500249966_20250101000000", sequence_id="2")
        apps = group_by_app([sf_a, sf_b], _cfg())
        assert len(apps["500249966_20250101000000"].files) == 2


# ---------------------------------------------------------------------------
# TC-3: Cross-debtor mismatch → quarantined with D-02 failure
# ---------------------------------------------------------------------------
class TestCrossDebtorMismatch:
    def _apps_with_mismatch(self):
        """Force two files with different debtors into the same AppRecord
        by giving them the same canonical ID via the _test suffix trick
        — not possible by design (different debtors always produce different
        canonicals). Instead we directly test _check_group_debtor_consistency
        by building a group manually after formation.
        """
        from scripts.ingest_lib import AppRecord, _check_group_debtor_consistency

        rec = AppRecord("111111111_20250101000000", "111111111_20250101000000")
        sf_a = _make_sf("111111111_20250101000000", sequence_id="1")
        sf_b = _make_sf("222222222_20250101000000", sequence_id="2")
        sf_b.app_id_raw = "222222222_20250101000000"  # different debtor
        rec.files = [sf_a, sf_b]
        _check_group_debtor_consistency(rec)
        return rec

    def test_quarantined_on_cross_debtor(self):
        rec = self._apps_with_mismatch()
        assert rec.quarantined is True

    def test_d02_failure_recorded(self):
        rec = self._apps_with_mismatch()
        assert "D-02-cross-session-identity-mismatch" in rec.validation_failures

    def test_same_debtor_not_quarantined_by_d02(self):
        sf_a = _make_sf("500249966_20250101000000", sequence_id="1")
        sf_b = _make_sf("500249966_20250101000000", sequence_id="2")
        apps = group_by_app([sf_a, sf_b], _cfg())
        rec = apps["500249966_20250101000000"]
        assert "D-02-cross-session-identity-mismatch" not in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-4 / TC-5: Edge cases
# ---------------------------------------------------------------------------
class TestEdgeCases:
    def test_empty_file_list_returns_empty_dict(self):
        assert group_by_app([], _cfg()) == {}

    def test_unclassified_files_skipped(self):
        sf = _make_sf(None)  # app_id_raw = None
        apps = group_by_app([sf], _cfg())
        assert len(apps) == 0, "Files with app_id_raw=None must be skipped"

    def test_mixed_classified_and_unclassified(self):
        sf_good = _make_sf("500249966_20250101000000")
        sf_bad = _make_sf(None)
        apps = group_by_app([sf_good, sf_bad], _cfg())
        assert len(apps) == 1

    def test_single_file_single_record(self):
        sf = _make_sf("500249966_20250101000000")
        apps = group_by_app([sf], _cfg())
        assert len(apps) == 1
        assert len(apps["500249966_20250101000000"].files) == 1


# ---------------------------------------------------------------------------
# TC-6: Different sequence_id → both files retained
# ---------------------------------------------------------------------------
class TestDifferentSequenceRetained:
    def test_different_sequences_not_deduped(self):
        files = [
            _make_sf("500249966_20250101000000", sequence_id=str(i))
            for i in range(1, 4)
        ]
        apps = group_by_app(files, _cfg())
        assert len(apps["500249966_20250101000000"].files) == 3
