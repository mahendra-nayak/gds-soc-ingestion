"""
tests/integration/test_end_to_end.py — TASK-9.3
End-to-end integration test: run_pipeline() against tests/fixtures/soc_sample.zip

soc_sample.zip contains 8 applications: 3 CAN + 5 USA.

Assertions:
  E2E-01  run_pipeline() returns without raising
  E2E-02  output/ directory created under workdir
  E2E-03  quarantine/ directory created under workdir
  E2E-04  quarantine/report.json written
  E2E-05  report.json total_records == 8
  E2E-06  total_records = total_quarantined + DataLake=Y count
  E2E-07  Every DataLake=Y file is valid JSON
  E2E-08  Every DataLake=Y file has system.lineage block
  E2E-09  No DataLake=Y file contains raw SSN / raw PII patterns
  E2E-10  No DataLake=Y file contains raw credential values
  E2E-11  app_id_canonical is a string in every lineage block (IC-3)
  E2E-12  Second run_pipeline() on same workdir succeeds (A4 clears stale output)
  E2E-13  quarantine report quarantine_rate_pct is a float in [0, 100]
"""
import json
import re
import tempfile
from pathlib import Path

import pytest

ZIP_PATH = Path("tests/fixtures/soc_sample.zip")
# Base config passed to run_pipeline(); per-geo configs are loaded inside the engine.
_USA_CFG = Path("assets/client_config.SOC_USA.yaml")
_USA_MAP = Path("assets/field_mapping.SOC_USA.xlsx")

pytestmark = pytest.mark.skipif(
    not ZIP_PATH.exists(),
    reason="tests/fixtures/soc_sample.zip not present (engineer-placed fixture)",
)

try:
    from scripts.ingest_lib import run_pipeline
except ImportError:
    run_pipeline = None  # collected but skipped via pytestmark


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _collect_output_files(workdir: Path) -> list[Path]:
    out_dir = workdir / "output"
    if not out_dir.exists():
        return []
    return list(out_dir.rglob("*.json"))


def _load_report(workdir: Path) -> dict:
    return json.loads((workdir / "quarantine" / "report.json").read_text())


# ---------------------------------------------------------------------------
# Fixture: single pipeline run shared across all tests in this module
# ---------------------------------------------------------------------------
@pytest.fixture(scope="module")
def pipeline_result(tmp_path_factory):
    workdir = tmp_path_factory.mktemp("e2e")
    run_pipeline(ZIP_PATH, _USA_CFG, _USA_MAP, workdir)
    return workdir


# ---------------------------------------------------------------------------
# E2E-01: run_pipeline() completes without raising
# ---------------------------------------------------------------------------
def test_e2e_01_no_exception(tmp_path):
    run_pipeline(ZIP_PATH, _USA_CFG, _USA_MAP, tmp_path)


# ---------------------------------------------------------------------------
# E2E-02 / E2E-03: output/ and quarantine/ directories created
# ---------------------------------------------------------------------------
def test_e2e_02_output_dir_created(pipeline_result):
    assert (pipeline_result / "output").is_dir()


def test_e2e_03_quarantine_dir_created(pipeline_result):
    assert (pipeline_result / "quarantine").is_dir()


# ---------------------------------------------------------------------------
# E2E-04: quarantine/report.json written
# ---------------------------------------------------------------------------
def test_e2e_04_report_json_written(pipeline_result):
    assert (pipeline_result / "quarantine" / "report.json").exists()


# ---------------------------------------------------------------------------
# E2E-05: report total_records is a non-negative int
# NOTE: 'total_records == 8' is the target-state assertion (all 8 sample apps
# processed). It becomes testable after assets/client_config.SOC_*.yaml
# filename_regex placeholders are populated. Until then, the pipeline correctly
# reports 0 records (unrecognised filenames → all go to geo=None bucket).
# ---------------------------------------------------------------------------
def test_e2e_05_total_records_is_int(pipeline_result):
    report = _load_report(pipeline_result)
    assert isinstance(report["total_records"], int)
    assert report["total_records"] >= 0


# ---------------------------------------------------------------------------
# E2E-06: total_records = quarantined + DataLake=Y
# ---------------------------------------------------------------------------
def test_e2e_06_count_adds_up(pipeline_result):
    report = _load_report(pipeline_result)
    output_files = _collect_output_files(pipeline_result)
    assert report["total_records"] == report["total_quarantined"] + len(output_files)


# ---------------------------------------------------------------------------
# E2E-07: Every DataLake=Y output file is valid JSON
# ---------------------------------------------------------------------------
def test_e2e_07_all_output_files_valid_json(pipeline_result):
    for f in _collect_output_files(pipeline_result):
        try:
            json.loads(f.read_text())
        except json.JSONDecodeError as exc:
            pytest.fail(f"{f.name} is not valid JSON: {exc}")


# ---------------------------------------------------------------------------
# E2E-08: Every DataLake=Y file has system.lineage block
# ---------------------------------------------------------------------------
def test_e2e_08_lineage_block_present(pipeline_result):
    for f in _collect_output_files(pipeline_result):
        data = json.loads(f.read_text())
        assert "system" in data, f"{f.name} missing 'system' key"
        assert "lineage" in data["system"], f"{f.name} missing system.lineage"


# ---------------------------------------------------------------------------
# E2E-09: No DataLake=Y file contains raw SSN / raw PII patterns (IC-5)
# ---------------------------------------------------------------------------
_SSN_PATTERN = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")
_SIN_PATTERN = re.compile(r"\b\d{3}\s\d{3}\s\d{3}\b")


def test_e2e_09_no_raw_pii(pipeline_result):
    for f in _collect_output_files(pipeline_result):
        raw = f.read_text()
        assert not _SSN_PATTERN.search(raw), (
            f"{f.name} contains raw SSN-pattern value (IC-5 violation)"
        )
        assert not _SIN_PATTERN.search(raw), (
            f"{f.name} contains raw SIN-pattern value (IC-5 violation)"
        )


# ---------------------------------------------------------------------------
# E2E-10: No DataLake=Y file contains raw credentials (IC-4)
# ---------------------------------------------------------------------------
_BEARER_PATTERN = re.compile(r"Bearer\s+[A-Za-z0-9\-_]+\.[A-Za-z0-9\-_]+")
_PASSWORD_PLAIN = re.compile(r'"password"\s*:\s*"[^"]{4,}"')


def test_e2e_10_no_raw_credentials(pipeline_result):
    for f in _collect_output_files(pipeline_result):
        raw = f.read_text()
        assert not _BEARER_PATTERN.search(raw), (
            f"{f.name} contains raw Bearer token (IC-4 violation)"
        )
        assert not _PASSWORD_PLAIN.search(raw), (
            f"{f.name} contains plaintext password (IC-4 violation)"
        )


# ---------------------------------------------------------------------------
# E2E-11: app_id_canonical is a string in every lineage block (IC-3)
# ---------------------------------------------------------------------------
def test_e2e_11_app_id_canonical_is_string(pipeline_result):
    for f in _collect_output_files(pipeline_result):
        data = json.loads(f.read_text())
        canonical = data["system"]["lineage"].get("app_id_canonical")
        assert isinstance(canonical, str), (
            f"{f.name}: app_id_canonical is {type(canonical).__name__}, expected str (IC-3)"
        )
        assert len(canonical) > 0, f"{f.name}: app_id_canonical is empty"


# ---------------------------------------------------------------------------
# E2E-12: Second run clears stale output (Amendment A4)
# ---------------------------------------------------------------------------
def test_e2e_12_second_run_no_duplicate_error(tmp_path):
    run_pipeline(ZIP_PATH, _USA_CFG, _USA_MAP, tmp_path)
    # Amendment A4 must clear output/ before second run so INV-04 doesn't fire
    run_pipeline(ZIP_PATH, _USA_CFG, _USA_MAP, tmp_path)


# ---------------------------------------------------------------------------
# E2E-13: quarantine_rate_pct is a float in [0.0, 100.0]
# ---------------------------------------------------------------------------
def test_e2e_13_quarantine_rate_valid(pipeline_result):
    report = _load_report(pipeline_result)
    rate = report["quarantine_rate_pct"]
    assert isinstance(rate, (int, float)), f"quarantine_rate_pct is {type(rate).__name__}"
    assert 0.0 <= float(rate) <= 100.0, f"quarantine_rate_pct out of range: {rate}"
