"""
tests/integration/test_dispatcher_wiring.py — TASK-1.5
Integration tests for dispatch_by_geo() wired into run_pipeline().

Invariant verified:
  INV-10: dispatch_by_geo() is called before scrub_credentials() in run_pipeline().
  Geography is determined from filename only; never from payload.

TC-1: 8-app ZIP dispatched → non-empty USA and CAN partitions
TC-2: each geo set processed with its matching config (verified via call-order mock)
TC-3: unroutable files not in output
TC-4: dispatch_by_geo() called before scrub_credentials() — call-order assertion
TC-5: total record count — PENDING (blocked on client_config.SOC_{geo}.yaml population)
"""
import shutil
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

import scripts.ingest_lib as engine
from scripts.ingest_lib import (
    ClientConfig,
    SourceFile,
    build_manifest,
    dispatch_by_geo,
    run_pipeline,
    unpack_zip,
)

FIXTURE_ZIP = Path("tests/fixtures/soc_sample.zip")
WORKDIR = Path("workdir/test_wiring")

# ---------------------------------------------------------------------------
# Minimal config stub — enough for manifest + dispatch (no pipeline execution)
# ---------------------------------------------------------------------------
_SOC_PATTERN = (
    r'^(?P<version>v\d+)'
    r'_(?P<geo>[A-Z]{2,3})'
    r'_(?P<debtor>\d{9})'
    r'_(?P<dt>\d{14})'
    r'(?:_(?P<test>test))?'
    r'_(?P<connector>C\d+)'
    r'_.*?'
    r'(?:_(?P<direction>request|response|req|resp))?'
    r'_\d{6,12}'
    r'_(?P<sequence_id>\d+)'
    r'(?:_(?P<step>\d+))?'
    r'(?:\.\w+)?$'
)

_MINIMAL_CFG_RAW = {
    "client": {"code": "SOC_USA", "schema_version": "1.1"},
    "config_version": "test",
    "package": {
        "folder_priority": [
            {"name": "cc_extracts", "required": False, "present_but_empty_ok": True},
            {"name": "data",        "required": True},
            {"name": "raw",         "required": True},
            {"name": "audit",       "required": True},
            {"name": "sdd",         "required": False},
        ],
        "tolerate_empty_folders": True,
    },
    "application_id": {
        "source": "filename_tokens",
        "filename": {
            "pattern": _SOC_PATTERN,
            "canonical_app_id_groups": ["debtor", "dt"],
        },
        "suffix_rules": [{"suffix": "_test", "action": "strip", "flag_lineage": True}],
    },
    "connectors": [],
    "sessions": {"model": "single"},
    "preprocess": {"credential_scrub": []},
    "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
    "validation": {
        "hard_quarantine_rules": ["REQ-VAL-001"],
        "soft_warn_rules": [],
        "client_params": {"valid_geographies": ["USA", "CAN"]},
    },
}


def _minimal_cfg() -> ClientConfig:
    return ClientConfig(_MINIMAL_CFG_RAW)


@pytest.fixture(autouse=True)
def cleanup_workdir():
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    yield
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)


# ---------------------------------------------------------------------------
# TC-1: 8-app ZIP → dispatch produces non-empty USA and CAN partitions
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not FIXTURE_ZIP.exists(), reason="soc_sample.zip not present")
class TestDispatchPartitionsFromRealZip:

    def _dispatch(self):
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        # SOC ZIP has a top-level SOC/ subfolder; descend into it
        inner = next((p for p in root.iterdir() if p.is_dir()), root)
        files = build_manifest(inner, _minimal_cfg())
        return dispatch_by_geo(files)

    def test_usa_partition_nonempty(self):
        result = self._dispatch()
        assert len(result["USA"]) > 0, "USA partition must be non-empty"

    def test_can_partition_nonempty(self):
        result = self._dispatch()
        assert len(result["CAN"]) > 0, "CAN partition must be non-empty"

    def test_both_partition_keys_present(self):
        result = self._dispatch()
        assert "USA" in result and "CAN" in result

    def test_total_files_conserved(self):
        """All classified files appear in exactly one partition."""
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        inner = next((p for p in root.iterdir() if p.is_dir()), root)
        files = build_manifest(inner, _minimal_cfg())
        classified = [sf for sf in files if sf.geography in ("USA", "CAN")]
        result = dispatch_by_geo(files)
        assert len(result["USA"]) + len(result["CAN"]) == len(classified)


# ---------------------------------------------------------------------------
# TC-3: Unroutable files (geography=None) not in any partition
# ---------------------------------------------------------------------------
class TestUnroutableNotInOutput:

    def test_none_geo_excluded_from_partitions(self):
        sf_usa = SourceFile(Path("usa.txt"), "raw", "C001", None, None,
                            "123456789_20250101000000", "1", geography="USA")
        sf_can = SourceFile(Path("can.txt"), "raw", "C001", None, None,
                            "123456789_20250101000001", "2", geography="CAN")
        sf_bad = SourceFile(Path("bad.txt"), "raw", None, None, None,
                            None, None, geography=None)

        result = dispatch_by_geo([sf_usa, sf_can, sf_bad])
        assert len(result["USA"]) == 1
        assert len(result["CAN"]) == 1
        total_in_partitions = len(result["USA"]) + len(result["CAN"])
        assert total_in_partitions == 2  # bad file not present in any partition


# ---------------------------------------------------------------------------
# TC-4: dispatch_by_geo() called before scrub_credentials() in run_pipeline()
# ---------------------------------------------------------------------------
@pytest.mark.skipif(not FIXTURE_ZIP.exists(), reason="soc_sample.zip not present")
class TestDispatchBeforeScrubCallOrder:

    def test_dispatch_before_scrub(self):
        """INV-10: dispatch_by_geo must precede scrub_credentials in run_pipeline()."""
        call_order: list[str] = []

        orig_dispatch = engine.dispatch_by_geo
        orig_scrub = engine.scrub_credentials

        def recording_dispatch(files):
            call_order.append("dispatch")
            return orig_dispatch(files)

        def recording_scrub(files, cfg):
            call_order.append("scrub")
            return []

        # Stub pipeline stages that need full config/mapping
        noop = lambda *a, **kw: None

        with (
            patch.object(engine, "dispatch_by_geo", side_effect=recording_dispatch),
            patch.object(engine, "scrub_credentials", side_effect=recording_scrub),
            patch.object(ClientConfig, "load", return_value=_minimal_cfg()),
            patch.object(engine, "load_mapping_sheet", return_value=[]),
            patch.object(engine, "parse_file", side_effect=noop),
            patch.object(engine, "group_by_app", return_value={}),
            patch.object(engine, "merge_sessions", side_effect=noop),
            patch.object(engine, "apply_mapping", side_effect=noop),
            patch.object(engine, "tokenise_pii", side_effect=noop),
            patch.object(engine, "assert_no_raw_pii", side_effect=noop),
            patch.object(engine, "build_lineage", side_effect=noop),
            patch.object(engine, "validate", side_effect=noop),
            patch.object(engine, "write_record", side_effect=noop),
        ):
            run_pipeline(
                FIXTURE_ZIP,
                "assets/client_config.SOC_USA.yaml",
                "assets/field_mapping.SOC_USA.xlsx",
                WORKDIR,
            )

        assert "dispatch" in call_order, "dispatch_by_geo was not called"
        assert "scrub" in call_order, "scrub_credentials was not called"
        assert call_order.index("dispatch") < call_order.index("scrub"), (
            "INV-10 VIOLATED: scrub_credentials called before dispatch_by_geo"
        )

    def test_geo_config_loaded_per_geography(self):
        """TC-2: A config load must occur for each non-empty geo partition."""
        load_calls: list[str] = []

        original_load = ClientConfig.load

        def recording_load(path):
            load_calls.append(str(path))
            return _minimal_cfg()

        noop = lambda *a, **kw: None

        with (
            patch.object(ClientConfig, "load", side_effect=recording_load),
            patch.object(engine, "load_mapping_sheet", return_value=[]),
            patch.object(engine, "parse_file", side_effect=noop),
            patch.object(engine, "group_by_app", return_value={}),
            patch.object(engine, "merge_sessions", side_effect=noop),
            patch.object(engine, "apply_mapping", side_effect=noop),
            patch.object(engine, "tokenise_pii", side_effect=noop),
            patch.object(engine, "assert_no_raw_pii", side_effect=noop),
            patch.object(engine, "build_lineage", side_effect=noop),
            patch.object(engine, "validate", side_effect=noop),
            patch.object(engine, "write_record", side_effect=noop),
        ):
            run_pipeline(
                FIXTURE_ZIP,
                "assets/client_config.SOC_USA.yaml",
                "assets/field_mapping.SOC_USA.xlsx",
                WORKDIR,
            )

        # Expect geo-specific config loads for USA and CAN
        geo_loads = [p for p in load_calls if "SOC_USA" in p or "SOC_CAN" in p]
        assert any("SOC_USA" in p for p in geo_loads), "SOC_USA config not loaded"
        assert any("SOC_CAN" in p for p in geo_loads), "SOC_CAN config not loaded"


# ---------------------------------------------------------------------------
# TC-5: Total record count — PENDING config population
# ---------------------------------------------------------------------------
class TestTotalRecordCount:
    @pytest.mark.skip(reason="PENDING: blocked on client_config.SOC_USA/CAN.yaml population (TASK-3/5, TASK-3/6)")
    def test_record_count_matches_expected(self):
        """Full pipeline integration check — requires populated configs and field mapping."""
        pass
