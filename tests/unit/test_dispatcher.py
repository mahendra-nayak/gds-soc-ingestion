"""
tests/unit/test_dispatcher.py — TASK-1.4
Tests for dispatch_by_geo() — deterministic geo-based file partitioning.

Invariant verified:
  INV-10: routing is explicit and deterministic. No default routing, silent
  fallback, or runtime inference. Unroutable files are logged as errors and
  excluded from both partitions.
"""
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from scripts.ingest_lib import SourceFile, dispatch_by_geo


def _sf(geography: str | None, app_id_raw: str | None = "123456789_20250101000000",
        name: str = "file.txt") -> SourceFile:
    """Build a minimal SourceFile stub with the given geography."""
    sf = SourceFile(
        path=Path(name),
        folder="raw",
        connector="C001",
        direction=None,
        step=None,
        app_id_raw=app_id_raw,
        sequence_id="1",
        geography=geography,
    )
    return sf


# ---------------------------------------------------------------------------
# TC-1: 5 USA + 3 CAN files → correct partition counts
# ---------------------------------------------------------------------------
class TestPartitionCounts:

    def test_usa_count(self):
        files = [_sf("USA", name=f"usa_{i}.txt") for i in range(5)] + \
                [_sf("CAN", name=f"can_{i}.txt") for i in range(3)]
        result = dispatch_by_geo(files)
        assert len(result["USA"]) == 5

    def test_can_count(self):
        files = [_sf("USA", name=f"usa_{i}.txt") for i in range(5)] + \
                [_sf("CAN", name=f"can_{i}.txt") for i in range(3)]
        result = dispatch_by_geo(files)
        assert len(result["CAN"]) == 3

    def test_both_keys_present(self):
        files = [_sf("USA", name=f"usa_{i}.txt") for i in range(5)] + \
                [_sf("CAN", name=f"can_{i}.txt") for i in range(3)]
        result = dispatch_by_geo(files)
        assert "USA" in result and "CAN" in result

    def test_files_not_duplicated(self):
        files = [_sf("USA", name=f"usa_{i}.txt") for i in range(5)] + \
                [_sf("CAN", name=f"can_{i}.txt") for i in range(3)]
        result = dispatch_by_geo(files)
        assert len(result["USA"]) + len(result["CAN"]) == 8


# ---------------------------------------------------------------------------
# TC-2: File with geography=None → unroutable; not in either partition
# ---------------------------------------------------------------------------
class TestNoneGeography:

    def test_not_in_usa(self):
        files = [_sf(None, name="unclassified.txt")]
        result = dispatch_by_geo(files)
        assert len(result["USA"]) == 0

    def test_not_in_can(self):
        files = [_sf(None, name="unclassified.txt")]
        result = dispatch_by_geo(files)
        assert len(result["CAN"]) == 0

    def test_error_logged(self, caplog):
        files = [_sf(None, name="unclassified.txt")]
        with caplog.at_level(logging.ERROR, logger="dg_forge.ingest"):
            dispatch_by_geo(files)
        assert any("QUARANTINE" in r.message for r in caplog.records)

    def test_no_exception(self):
        try:
            dispatch_by_geo([_sf(None, name="unclassified.txt")])
        except Exception as e:
            pytest.fail(f"dispatch_by_geo raised unexpectedly: {e}")


# ---------------------------------------------------------------------------
# TC-3: Empty file list → {'USA': [], 'CAN': []} — no KeyError, no exception
# ---------------------------------------------------------------------------
class TestEmptyList:

    def test_returns_both_keys(self):
        result = dispatch_by_geo([])
        assert result == {"USA": [], "CAN": []}

    def test_no_exception(self):
        try:
            dispatch_by_geo([])
        except Exception as e:
            pytest.fail(f"dispatch_by_geo raised on empty list: {e}")


# ---------------------------------------------------------------------------
# TC-4: Unclassified file (app_id_raw=None, geography=None) → unroutable
# ---------------------------------------------------------------------------
class TestUnclassifiedFile:

    def test_not_in_any_partition(self):
        sf = _sf(None, app_id_raw=None, name="bad_filename.txt")
        result = dispatch_by_geo([sf])
        assert len(result["USA"]) == 0
        assert len(result["CAN"]) == 0

    def test_error_logged(self, caplog):
        sf = _sf(None, app_id_raw=None, name="bad_filename.txt")
        with caplog.at_level(logging.ERROR, logger="dg_forge.ingest"):
            dispatch_by_geo([sf])
        assert any("QUARANTINE" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# TC-5: Geography never inferred — INV-10
# ---------------------------------------------------------------------------
class TestNoGeoInference:

    def test_unrecognised_geo_not_routed(self):
        """A file with a non-CAN/USA geography must not appear in any partition."""
        sf = _sf("MEX", name="mex_file.txt")
        result = dispatch_by_geo([sf])
        assert len(result["USA"]) == 0
        assert len(result["CAN"]) == 0

    def test_mixed_valid_and_unroutable(self):
        """Unroutable files don't contaminate valid partitions."""
        files = [
            _sf("USA", name="usa.txt"),
            _sf(None, name="none_geo.txt"),
            _sf("MEX", name="mex.txt"),
            _sf("CAN", name="can.txt"),
        ]
        result = dispatch_by_geo(files)
        assert len(result["USA"]) == 1
        assert len(result["CAN"]) == 1
