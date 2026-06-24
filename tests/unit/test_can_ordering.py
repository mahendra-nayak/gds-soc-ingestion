"""
tests/unit/test_can_ordering.py — TASK-3.4
Unit tests for CAN session ordering check in _check_can_session_order().

D-01: IF geography=CAN AND both sessions present THEN EFX.timestamp > TU.timestamp.
Violation is a soft-warn (REQ-BL-002). Record does NOT quarantine on ordering
anomaly alone — only the lineage flag and validation_failures entry are set.

TC-1: EFX later than TU → no anomaly flag, no REQ-BL-002
TC-2: EFX earlier than TU → session_order_anomaly=True, REQ-BL-002 in failures
TC-3: Equal timestamps → session_order_anomaly=True (strictly greater required)
TC-4: No datetimes set → check skipped gracefully (no error, no flag)
TC-5: Ordering anomaly does NOT set rec.quarantined (soft-warn only)
"""
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.ingest_lib import AppRecord, SourceFile
from scripts.ingest_lib import _check_can_session_order


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _ts(year: int, month: int, day: int, hour: int = 0) -> datetime:
    return datetime(year, month, day, hour, tzinfo=timezone.utc)


def _make_sf(connector: str, dt: datetime | None) -> SourceFile:
    sf = SourceFile(
        path=Path(f"fake/raw/{connector}_file.txt"),
        folder="raw",
        connector=connector,
        direction="REQ",
        step=None,
        app_id_raw="600249966_20250101000000",
        sequence_id="1",
        geography="CAN",
    )
    sf.datetime = dt
    return sf


def _make_rec(tu_dt: datetime | None, efx_dt: datetime | None,
              efx_connector: str = "C161653") -> AppRecord:
    rec = AppRecord("600249966_20250101000000", "600249966_20250101000000",
                    geography="CAN")
    rec.files = [
        _make_sf("C100810", tu_dt),
        _make_sf(efx_connector, efx_dt),
    ]
    return rec


# ---------------------------------------------------------------------------
# TC-1: EFX later than TU → no anomaly
# ---------------------------------------------------------------------------
class TestEfxLaterThanTu:
    def test_no_anomaly_flag(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 1, 10), efx_dt=_ts(2025, 1, 1, 11))
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is None

    def test_no_req_bl_002(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 1), efx_dt=_ts(2025, 1, 2))
        _check_can_session_order(rec)
        assert "REQ-BL-002" not in rec.validation_failures

    def test_not_quarantined(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 1), efx_dt=_ts(2025, 1, 2))
        _check_can_session_order(rec)
        assert rec.quarantined is False


# ---------------------------------------------------------------------------
# TC-2: EFX earlier than TU → soft-warn (REQ-BL-002)
# ---------------------------------------------------------------------------
class TestEfxEarlierThanTu:
    def test_session_order_anomaly_set(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 2), efx_dt=_ts(2025, 1, 1))
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is True

    def test_req_bl_002_in_failures(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 2), efx_dt=_ts(2025, 1, 1))
        _check_can_session_order(rec)
        assert "REQ-BL-002" in rec.validation_failures

    def test_c161796_also_triggers_ordering_check(self):
        rec = _make_rec(tu_dt=_ts(2025, 1, 2), efx_dt=_ts(2025, 1, 1),
                        efx_connector="C161796")
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is True


# ---------------------------------------------------------------------------
# TC-3: Equal timestamps → anomaly (strictly greater required)
# ---------------------------------------------------------------------------
class TestEqualTimestamps:
    def test_equal_timestamps_flagged_as_anomaly(self):
        ts = _ts(2025, 6, 15, 14)
        rec = _make_rec(tu_dt=ts, efx_dt=ts)
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is True

    def test_equal_timestamps_req_bl_002(self):
        ts = _ts(2025, 6, 15, 14)
        rec = _make_rec(tu_dt=ts, efx_dt=ts)
        _check_can_session_order(rec)
        assert "REQ-BL-002" in rec.validation_failures


# ---------------------------------------------------------------------------
# TC-4: No datetimes → check skipped gracefully
# ---------------------------------------------------------------------------
class TestNoDatetimes:
    def test_no_error_when_no_datetimes(self):
        rec = _make_rec(tu_dt=None, efx_dt=None)
        _check_can_session_order(rec)  # must not raise

    def test_no_anomaly_flag_when_no_datetimes(self):
        rec = _make_rec(tu_dt=None, efx_dt=None)
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is None

    def test_partial_datetimes_skipped(self):
        """Only TU datetime set, EFX absent → check skipped."""
        rec = _make_rec(tu_dt=_ts(2025, 1, 1), efx_dt=None)
        _check_can_session_order(rec)
        assert rec.lineage.get("session_order_anomaly") is None


# ---------------------------------------------------------------------------
# TC-5: Ordering anomaly does NOT quarantine record (soft-warn)
# ---------------------------------------------------------------------------
class TestSoftWarnDoesNotQuarantine:
    def test_quarantined_false_on_ordering_anomaly(self):
        """D-01 violation is soft-warn — must not set rec.quarantined."""
        rec = _make_rec(tu_dt=_ts(2025, 1, 2), efx_dt=_ts(2025, 1, 1))
        _check_can_session_order(rec)
        assert rec.quarantined is False, (
            "Ordering anomaly (D-01) is soft-warn — must not quarantine record"
        )
