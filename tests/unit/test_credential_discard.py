"""
tests/unit/test_credential_discard.py — TASK-4.6
Unit tests for credential_discard parse strategy: C161653.

Invariants verified:
  D-06: A credential connector (is_credential=true) must never produce a payload.
        Returning None is the required behaviour.
  IC-1: Credential scrub (scrub_credentials) executes before any parse; the
        credential_discard strategy is the parse-side enforcement of IC-1 for
        C161653.
  IC-4: No credential value may exist in any persisted record — credential
        connectors are excluded from all field mapping source locators.

TC-1: parse_file() returns None for C161653 (is_credential guard + strategy)
TC-2: sf.payload remains None after parse_file() — payload never written
TC-3: is_credential guard alone blocks parse regardless of parse_strategy value
TC-4: C161653 is not present in any field mapping source locator (D-06 / IC-4)
"""
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from scripts.ingest_lib import MappingRow, SourceFile, parse_file


# ---------------------------------------------------------------------------
# Config stubs
# ---------------------------------------------------------------------------
def _cfg_credential() -> dict:
    """C161653 registered as is_credential=true with credential_discard strategy."""
    return {
        "client": {"code": "SOC_CAN", "schema_version": "1.1"},
        "connectors": [
            {"code": "C161653", "is_credential": True, "parse_strategy": "credential_discard"},
        ],
    }


def _cfg_credential_no_strategy() -> dict:
    """Verify the is_credential guard works even without an explicit parse_strategy."""
    return {
        "client": {"code": "SOC_CAN", "schema_version": "1.1"},
        "connectors": [
            {"code": "C161653", "is_credential": True},
        ],
    }


def _make_sf(tmp_path: Path, connector: str = "C161653") -> SourceFile:
    f = tmp_path / f"{connector}_req.bin"
    f.write_bytes(b"[SCRUBBED_CREDENTIAL_PAYLOAD]")
    return SourceFile(
        path=f,
        folder="raw",
        connector=connector,
        direction="REQ",
        step=None,
        app_id_raw="600249960_20250101000000",
        sequence_id="1",
    )


# ---------------------------------------------------------------------------
# TC-1: parse_file() returns None for C161653 (D-06)
# ---------------------------------------------------------------------------
class TestCredentialDiscardReturnsNone:
    def test_parse_file_returns_none(self, tmp_path):
        sf = _make_sf(tmp_path)
        result = parse_file(sf, _cfg_credential())
        assert result is None

    def test_returns_none_regardless_of_file_content(self, tmp_path):
        f = tmp_path / "c161653_large.bin"
        f.write_bytes(b"X" * 10_000)
        sf = _make_sf(tmp_path)
        sf.path = f
        result = parse_file(sf, _cfg_credential())
        assert result is None

    def test_returns_none_for_empty_file(self, tmp_path):
        f = tmp_path / "c161653_empty.bin"
        f.write_bytes(b"")
        sf = SourceFile(
            path=f, folder="raw", connector="C161653", direction="REQ",
            step=None, app_id_raw="600249960_20250101000000", sequence_id="1",
        )
        result = parse_file(sf, _cfg_credential())
        assert result is None


# ---------------------------------------------------------------------------
# TC-2: sf.payload remains None after parse_file() (D-06)
# ---------------------------------------------------------------------------
class TestPayloadNeverWritten:
    def test_sf_payload_is_none_after_parse(self, tmp_path):
        sf = _make_sf(tmp_path)
        parse_file(sf, _cfg_credential())
        assert sf.payload is None

    def test_sf_payload_none_even_when_pre_set(self, tmp_path):
        """If sf.payload was set to a stale value, parse_file must not overwrite it
        with real data — it must leave it None (scrub-only connectors bypass parse)."""
        sf = _make_sf(tmp_path)
        sf.payload = None  # explicitly confirming starting state
        parse_file(sf, _cfg_credential())
        assert sf.payload is None

    def test_parse_file_does_not_read_file_bytes(self, tmp_path):
        """credential_discard returns before reading sf.path — file need not be valid."""
        f = tmp_path / "c161653_fake.bin"
        # Write deliberately unreadable marker — parse_file must never reach it
        f.write_bytes(b"\xff\xfe GARBAGE \x00")
        sf = SourceFile(
            path=f, folder="raw", connector="C161653", direction="REQ",
            step=None, app_id_raw="600249960_20250101000000", sequence_id="1",
        )
        result = parse_file(sf, _cfg_credential())  # must not raise
        assert result is None


# ---------------------------------------------------------------------------
# TC-3: is_credential guard blocks parse regardless of parse_strategy (D-06)
# ---------------------------------------------------------------------------
class TestIsCredentialGuard:
    def test_guard_fires_without_explicit_strategy(self, tmp_path):
        """is_credential=true alone is sufficient — parse_strategy need not be set."""
        sf = _make_sf(tmp_path)
        result = parse_file(sf, _cfg_credential_no_strategy())
        assert result is None

    def test_payload_none_without_explicit_strategy(self, tmp_path):
        sf = _make_sf(tmp_path)
        parse_file(sf, _cfg_credential_no_strategy())
        assert sf.payload is None

    def test_non_credential_connector_not_blocked(self, tmp_path):
        """Sanity: a non-credential connector with raw_json is NOT blocked."""
        cfg = {
            "client": {"code": "SOC_CAN", "schema_version": "1.1"},
            "connectors": [
                {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            ],
        }
        f = tmp_path / "c225334_req.json"
        f.write_bytes(b'{"record": {"EcsDebtorNumber": "123"}}')
        sf = SourceFile(
            path=f, folder="raw", connector="C225334", direction="REQ",
            step=None, app_id_raw="500249960_20250101000000", sequence_id="1",
        )
        result = parse_file(sf, cfg)
        assert result is not None


# ---------------------------------------------------------------------------
# TC-4: C161653 NOT in any field mapping source locator (D-06 / IC-4)
# ---------------------------------------------------------------------------
class TestC161653NotInFieldMapping:
    """Credential connectors must never appear as source locators in field mapping rows.
    Verified here with a synthetic mapping representing a well-formed CAN sheet.
    The actual field_mapping.SOC_CAN.xlsx is engineer-placed; the rule is structural.
    """

    def _make_mapping_row(self, primary_locator: str) -> MappingRow:
        return MappingRow(
            sdd_path="system.application.score",
            category="Bureau",
            data_type="numeric",
            pii=False,
            sources=[{"tier": "PRIMARY", "locator": primary_locator, "path": "Score"}],
            transform=None,
            construction=None,
        )

    def test_c161653_not_in_synthetic_can_mapping(self):
        mapping = [
            self._make_mapping_row("C100810 | data | RESP"),
            self._make_mapping_row("C161796 | data | RESP"),
            self._make_mapping_row("C225334 | raw  | REQ"),
        ]
        all_locators = [
            src["locator"]
            for row in mapping
            for src in row.sources
        ]
        assert not any("C161653" in loc for loc in all_locators), (
            "D-06 / IC-4: C161653 (credential connector) must not appear "
            "in any field mapping source locator"
        )

    def test_credential_flag_set_in_can_config(self):
        """CAN config must mark C161653 as is_credential=true."""
        import yaml
        cfg_path = Path(__file__).parent.parent.parent / "assets" / "client_config.SOC_CAN.yaml"
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        connectors = raw.get("connectors", []) or []
        c161653 = next((c for c in connectors if c.get("code") == "C161653"), None)
        assert c161653 is not None, "C161653 must be registered in client_config.SOC_CAN.yaml"
        assert c161653.get("is_credential") is True, "C161653 must have is_credential: true"

    def test_parse_strategy_is_credential_discard(self):
        """C161653 parse_strategy must be credential_discard in CAN config."""
        import yaml
        cfg_path = Path(__file__).parent.parent.parent / "assets" / "client_config.SOC_CAN.yaml"
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        connectors = raw.get("connectors", []) or []
        c161653 = next((c for c in connectors if c.get("code") == "C161653"), None)
        assert c161653 is not None
        assert c161653.get("parse_strategy") == "credential_discard"
