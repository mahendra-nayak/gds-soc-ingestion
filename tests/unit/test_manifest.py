"""
tests/unit/test_manifest.py — TASK-1.2
Smoke test for unpack_zip() + build_manifest() against the real SOC fixture.
No mocking — calls real functions against real fixture.
"""
import os
import shutil
import pytest
from pathlib import Path

from scripts.ingest_lib import unpack_zip, build_manifest, ClientConfig

FIXTURE_ZIP = Path("tests/fixtures/soc_sample.zip")
WORKDIR = Path("workdir/test_manifest")


@pytest.fixture(autouse=True)
def cleanup_workdir():
    """Remove workdir before and after each test."""
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)
    yield
    if WORKDIR.exists():
        shutil.rmtree(WORKDIR)


def _minimal_config() -> ClientConfig:
    """
    Minimal ClientConfig stub covering all 5 SOC folder names and a
    permissive filename_tokens regex that matches any SOC filename.
    """
    return ClientConfig({
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
                # Permissive regex — captures connector and debtor from any SOC filename
                "pattern": r"^(?P<version>v\d+)_(?P<geo>CAN|USA)_(?P<debtor>\d+)_(?P<dt>\d{14})(?:_(?P<test>test))?_(?P<connector>C\d+)_.*$",
                "canonical_app_id_groups": ["debtor", "dt"],
            },
        },
        "connectors": [],
    })


@pytest.mark.skipif(
    not FIXTURE_ZIP.exists(),
    reason="soc_sample.zip not present — engineer must place it in tests/fixtures/",
)
class TestManifestSmoke:

    def test_unpack_zip_succeeds(self):
        """8-app ZIP unpacks without error."""
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        assert root.exists(), "workdir root should exist after unpack"

    def test_manifest_returns_files(self):
        """Manifest returns files from all non-empty folders."""
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        # ZIP has a top-level SOC/ subfolder; descend into it
        inner = next((p for p in root.iterdir() if p.is_dir()), root)
        cfg = _minimal_config()
        files = build_manifest(inner, cfg)
        assert len(files) > 0, "manifest must return at least one file"

    def test_all_files_have_folder(self):
        """Every SourceFile has a non-None folder attribute."""
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        inner = next((p for p in root.iterdir() if p.is_dir()), root)
        cfg = _minimal_config()
        files = build_manifest(inner, cfg)
        assert all(sf.folder is not None for sf in files), (
            "every SourceFile must have a folder set"
        )

    def test_empty_cc_extracts_tolerated(self):
        """Empty cc_extracts/ folder does not raise an exception."""
        root = unpack_zip(FIXTURE_ZIP, WORKDIR)
        inner = next((p for p in root.iterdir() if p.is_dir()), root)
        cfg = _minimal_config()
        # Should complete without raising even though cc_extracts/ is empty
        try:
            build_manifest(inner, cfg)
        except Exception as e:
            pytest.fail(f"build_manifest raised unexpectedly on empty cc_extracts/: {e}")
