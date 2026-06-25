"""
tests/unit/test_source_priority.py — TASK-5.5
Unit tests for resolve_source() source priority resolution and D-12 enforcement.

D-12: Source priority is determined solely by tier order in the MappingRow.
      No runtime heuristic may select a lower-priority source because the
      higher-priority has 'more complete' data. Standard fallback (null → try
      next tier) is the only permitted runtime source selection mechanism.

TC-1: PRIMARY non-null → PRIMARY value used; SECONDARY ignored
TC-2: PRIMARY null → SECONDARY value used (standard fallback)
TC-3: All sources null → None returned
TC-4: D-12 — richer PRIMARY overrides SECONDARY regardless of content richness
TC-5: TERTIARY reached only when PRIMARY+SECONDARY both null
"""
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _get_path,
    apply_mapping,
    resolve_source,
)
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec(*files) -> AppRecord:
    rec = AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )
    rec.files = list(files)
    return rec


def _make_sf(connector: str, direction: str, payload, folder: str = "raw") -> SourceFile:
    return SourceFile(
        path=Path(f"fake/{folder}/{connector}_{direction}.json"),
        folder=folder,
        connector=connector,
        direction=direction,
        step=None,
        app_id_raw="500249960_20250101000000",
        sequence_id="1",
        payload=payload,
    )


def _multi_row(sdd_path: str, sources: list, transform: str = None) -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Attribute",
        data_type="string",
        pii=False,
        sources=sources,
        transform=transform,
        construction=None,
    )


def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C78098", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C78449", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# TC-1: PRIMARY non-null → PRIMARY used; SECONDARY not accessed
# ---------------------------------------------------------------------------
class TestPrimaryUsed:
    def test_primary_non_null_returns_primary(self):
        primary_sf = _make_sf("C225334", "RESP", {"record": {"field": "primary_value"}})
        secondary_sf = _make_sf("C78098", "RESP", {"data": {"field": "secondary_value"}})
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "primary_value"

    def test_primary_used_secondary_not_checked(self):
        """When PRIMARY resolves, SECONDARY payload is None — should still return PRIMARY."""
        primary_sf = _make_sf("C225334", "RESP", {"record": {"field": "from_primary"}})
        secondary_sf = _make_sf("C78098", "RESP", None)   # payload None — would fail if accessed
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "from_primary"


# ---------------------------------------------------------------------------
# TC-2: PRIMARY null → SECONDARY used (standard fallback)
# ---------------------------------------------------------------------------
class TestSecondaryFallback:
    def test_null_primary_falls_through_to_secondary(self):
        primary_sf = _make_sf("C225334", "RESP", {"record": {}})   # field absent → None
        secondary_sf = _make_sf("C78098", "RESP", {"data": {"field": "from_secondary"}})
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "from_secondary"

    def test_missing_connector_falls_through(self):
        """Primary connector absent from rec.files entirely → falls to secondary."""
        secondary_sf = _make_sf("C78098", "RESP", {"data": {"field": "backup_val"}})
        rec = _make_rec(secondary_sf)   # no C225334 in files
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "backup_val"

    def test_empty_string_primary_falls_through(self):
        """Empty string in PRIMARY treated as absent → SECONDARY used."""
        primary_sf = _make_sf("C225334", "RESP", {"record": {"field": ""}})
        secondary_sf = _make_sf("C78098", "RESP", {"data": {"field": "second"}})
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "second"


# ---------------------------------------------------------------------------
# TC-3: All sources null → None returned
# ---------------------------------------------------------------------------
class TestAllSourcesNull:
    def test_all_null_returns_none(self):
        sf1 = _make_sf("C225334", "RESP", {"record": {}})
        sf2 = _make_sf("C78098", "RESP", {"data": {}})
        rec = _make_rec(sf1, sf2)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result is None

    def test_no_sources_returns_none(self):
        rec = _make_rec()
        row = _multi_row("some.path", sources=[])
        result = resolve_source(rec, row, _cfg())
        assert result is None

    def test_all_connectors_absent_returns_none(self):
        rec = _make_rec()   # no files at all
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result is None


# ---------------------------------------------------------------------------
# TC-4: D-12 — tier order is the only selection criterion
# ---------------------------------------------------------------------------
class TestD12Enforcement:
    def test_richer_secondary_not_preferred_over_populated_primary(self):
        """D-12: PRIMARY wins even if SECONDARY has 'more' data.
        Only null/empty triggers fallback — richness is not considered."""
        primary_sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        secondary_sf = _make_sf(
            "C78098",
            "RESP",
            {"data": {"FICO": "720", "extra_key": "bonus_data"}},
        )
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "system.application.scores.score1",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.FICO"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.FICO"},
            ],
            transform="string_to_numeric",
        )
        result = resolve_source(rec, row, _cfg())
        # PRIMARY has 680 — SECONDARY (720) must not override it
        assert result == "680"

    def test_secondary_used_only_when_primary_null(self):
        """D-12 complement: SECONDARY IS used — but only because PRIMARY was null."""
        primary_sf = _make_sf("C225334", "RESP", {"record": {}})   # FICO absent
        secondary_sf = _make_sf("C78098", "RESP", {"data": {"FICO": "720"}})
        rec = _make_rec(primary_sf, secondary_sf)
        row = _multi_row(
            "system.application.scores.score1",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.FICO"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.FICO"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "720"


# ---------------------------------------------------------------------------
# TC-5: TERTIARY reached only when PRIMARY+SECONDARY both null
# ---------------------------------------------------------------------------
class TestTertiaryFallback:
    def test_tertiary_used_when_primary_and_secondary_null(self):
        sf1 = _make_sf("C225334", "RESP", {"record": {}})
        sf2 = _make_sf("C78098", "RESP", {"data": {}})
        sf3 = _make_sf("C78449", "RESP", {"payload": {"field": "tertiary_value"}})
        rec = _make_rec(sf1, sf2, sf3)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
                {"tier": "TERTIARY", "locator": "C78449 | raw | RESP", "path": "payload.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "tertiary_value"

    def test_primary_non_null_skips_secondary_and_tertiary(self):
        sf1 = _make_sf("C225334", "RESP", {"record": {"field": "primary_val"}})
        sf2 = _make_sf("C78098", "RESP", {"data": {"field": "secondary_val"}})
        sf3 = _make_sf("C78449", "RESP", {"payload": {"field": "tertiary_val"}})
        rec = _make_rec(sf1, sf2, sf3)
        row = _multi_row(
            "some.path",
            sources=[
                {"tier": "PRIMARY", "locator": "C225334 | raw | RESP", "path": "record.field"},
                {"tier": "SECONDARY", "locator": "C78098 | raw | RESP", "path": "data.field"},
                {"tier": "TERTIARY", "locator": "C78449 | raw | RESP", "path": "payload.field"},
            ],
        )
        result = resolve_source(rec, row, _cfg())
        assert result == "primary_val"
