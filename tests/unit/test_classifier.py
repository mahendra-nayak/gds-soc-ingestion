"""
tests/unit/test_classifier.py — TASK-1.3
Tests for _classify_file() — SOC filename token parser.

Invariants verified:
  INV-07: app_id_raw is always a str (VARCHAR); no numeric cast.
  INV-10: geography set only from explicit geo group; never inferred.
  Amendment A1: no-match filenames produce warning + None fields; no exception.
"""
import logging
from pathlib import Path

import pytest

from scripts.ingest_lib import ClientConfig, SourceFile, _classify_file

# ---------------------------------------------------------------------------
# SOC filename regex — must provide all named groups required by the spec.
# Format: {version}_{geo}_{debtor}_{dt}[_test]_{connector}_{name}[_{direction}]_{ts}_{seq}[_{step}].{ext}
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


def _cfg() -> ClientConfig:
    """Minimal ClientConfig stub for filename_tokens classification."""
    return ClientConfig({
        "application_id": {
            "source": "filename_tokens",
            "filename": {
                "pattern": _SOC_PATTERN,
                "canonical_app_id_groups": ["debtor", "dt"],
            },
        },
        "connectors": [],
    })


def _sf(filename: str) -> SourceFile:
    """Run _classify_file() against a synthetic Path with the given filename."""
    p = Path(filename)
    return _classify_file(p, folder="raw", cfg=_cfg())


# ---------------------------------------------------------------------------
# TC-1: Standard USA filename
# ---------------------------------------------------------------------------
class TestUSAFilename:
    FNAME = "v51_USA_500249966_20250707150115_C225334_web_service_request_155537657_78_3.json"

    def test_geo(self):
        assert _sf(self.FNAME).geography == "USA"

    def test_debtor_extracted(self):
        sf = _sf(self.FNAME)
        assert "500249966" in sf.app_id_raw

    def test_connector(self):
        assert _sf(self.FNAME).connector == "C225334"

    def test_direction_req(self):
        assert _sf(self.FNAME).direction == "REQ"

    def test_sequence_id_is_str(self):
        sf = _sf(self.FNAME)
        assert sf.sequence_id == "78"
        assert isinstance(sf.sequence_id, str)  # INV-07 / IC-3

    def test_app_id_raw_is_str(self):
        sf = _sf(self.FNAME)
        assert isinstance(sf.app_id_raw, str)   # INV-07: never numeric
        assert sf.app_id_raw == "500249966_20250707150115"

    def test_no_test_suffix(self):
        assert not _sf(self.FNAME).app_id_raw.endswith("_test")


# ---------------------------------------------------------------------------
# TC-2: Standard CAN filename
# ---------------------------------------------------------------------------
class TestCANFilename:
    FNAME = "v51_CAN_502417181_20250401134139_C215125_database_extracts_request_110611582_74_5.json"

    def test_geo(self):
        assert _sf(self.FNAME).geography == "CAN"

    def test_debtor_extracted(self):
        assert "502417181" in _sf(self.FNAME).app_id_raw

    def test_connector(self):
        assert _sf(self.FNAME).connector == "C215125"

    def test_direction_req(self):
        assert _sf(self.FNAME).direction == "REQ"

    def test_app_id_raw_is_str(self):
        sf = _sf(self.FNAME)
        assert isinstance(sf.app_id_raw, str)
        assert sf.app_id_raw == "502417181_20250401134139"


# ---------------------------------------------------------------------------
# TC-3: _test suffix filename
# ---------------------------------------------------------------------------
class TestTestSuffix:
    FNAME = "v51_USA_500249966_20240930064253_test_C225334_web_service_request_110641906_77_14.json"

    def test_geo(self):
        assert _sf(self.FNAME).geography == "USA"

    def test_app_id_raw_contains_test(self):
        sf = _sf(self.FNAME)
        assert sf.app_id_raw == "500249966_20240930064253_test"
        assert sf.app_id_raw.endswith("_test")

    def test_app_id_raw_is_str(self):
        assert isinstance(_sf(self.FNAME).app_id_raw, str)  # INV-07


# ---------------------------------------------------------------------------
# TC-4: Unrecognised geo token — INV-10
# ---------------------------------------------------------------------------
class TestUnrecognisedGeo:
    FNAME = "v51_MEX_500249966_20250707150115_C225334_web_service_request_155537657_78.json"

    def test_geography_is_none(self):
        # INV-10: unrecognised geo → None; no inference attempted
        assert _sf(self.FNAME).geography is None

    def test_no_exception_raised(self):
        try:
            _sf(self.FNAME)
        except Exception as e:
            pytest.fail(f"_classify_file raised unexpectedly for bad geo: {e}")

    def test_warning_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger="dg_forge.ingest"):
            _sf(self.FNAME)
        assert any("UNRECOGNISED geo" in r.message for r in caplog.records)

    def test_connector_still_extracted(self):
        # Rest of the fields still parsed even when geo is invalid
        assert _sf(self.FNAME).connector == "C225334"


# ---------------------------------------------------------------------------
# TC-5: Filename not matching pattern at all — Amendment A1
# ---------------------------------------------------------------------------
class TestNoMatch:
    FNAME = "some_random_unrelated_file.txt"

    def test_app_id_raw_is_none(self):
        assert _sf(self.FNAME).app_id_raw is None

    def test_geography_is_none(self):
        assert _sf(self.FNAME).geography is None

    def test_no_exception_raised(self):
        try:
            _sf(self.FNAME)
        except Exception as e:
            pytest.fail(f"_classify_file raised unexpectedly on no-match: {e}")

    def test_warning_logged(self, caplog):
        with caplog.at_level(logging.WARNING, logger="dg_forge.ingest"):
            _sf(self.FNAME)
        assert any("UNCLASSIFIED" in r.message for r in caplog.records)

    def test_connector_is_none(self):
        assert _sf(self.FNAME).connector is None


# ---------------------------------------------------------------------------
# TC-6: BUG-01 — direction fallback when regex has no direction group
# ---------------------------------------------------------------------------
_PROD_PATTERN = (
    r'^v\d+_(?P<geo>USA|CAN)_(?P<debtor>\d+)_(?P<dt>\d{14})'
    r'(?P<test>_test)?_(?P<connector>C\d+)_.+_(?P<sequence_id>\d{7,12})'
    r'_(?P<step>\d{1,4})(?:_\d+)?\.\w+$'
)


def _prod_cfg() -> ClientConfig:
    """Config using production regex — no direction named group."""
    return ClientConfig({
        "application_id": {
            "source": "filename_tokens",
            "filename": {
                "pattern": _PROD_PATTERN,
                "canonical_app_id_groups": ["debtor", "dt"],
            },
        },
        "connectors": [],
    })


def _sf_prod(filename: str) -> SourceFile:
    return _classify_file(Path(filename), folder="raw", cfg=_prod_cfg())


class TestDirectionFallback:
    """BUG-01: when regex has no direction group, direction is derived from filename stem."""

    def test_response_in_stem_gives_resp(self):
        fname = (
            "v51_USA_100226802_20250707150115_C225334"
            "_web_service_cc_response_155537657_78_3.json"
        )
        assert _sf_prod(fname).direction == "RESP"

    def test_request_in_stem_gives_req(self):
        fname = (
            "v51_USA_100226802_20250707150115_C225334"
            "_database___extracts_request_110611582_74_5.json"
        )
        assert _sf_prod(fname).direction == "REQ"

    def test_no_direction_token_gives_none(self):
        fname = (
            "v51_USA_100226802_20250707150115_C78098"
            "_gds_bureau_credit_pull_155537657_79_1.json"
        )
        assert _sf_prod(fname).direction is None
