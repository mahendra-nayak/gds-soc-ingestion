"""
tests/unit/test_extra_columns.py — TASK-6.4
Unit tests for ExtraColumns group registration and routing in apply_mapping().

D-13: extra_columns must remain separate from the core schema record.
  Unmapped / extra-columns-designated fields → rec.extra_columns[group_name][field_name]
  Never written to rec.record root.

Groups registered in both configs:
  SOC_pygdsa_attributes    — C103403
  SOC_derived_application  — C225334
  SOC_decision_variable    — C225334
  SOC_decision_req         — C238743

TC-1: MappingRow with sdd_path='extra_columns.*' → written to rec.extra_columns, not rec.record
TC-2: All four group names writable to rec.extra_columns
TC-3: rec.record root has no extra_columns key after routing
TC-4: Both YAML configs have all four extra_columns_groups registered
TC-5: Normal MappingRow (no extra_columns prefix) still writes to rec.record
"""
import yaml
import pytest

from scripts.ingest_lib import (
    AppRecord,
    MappingRow,
    SourceFile,
    _get_path,
    apply_mapping,
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


def _ec_row(group: str, connector: str, field_path: str,
            transform: str = None) -> MappingRow:
    return MappingRow(
        sdd_path=f"extra_columns.{group}",
        category="ExtraColumn",
        data_type="object",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | raw | RESP",
            "path": field_path,
        }],
        transform=transform,
        construction=None,
    )


def _std_row(sdd_path: str, connector: str, field_path: str) -> MappingRow:
    return MappingRow(
        sdd_path=sdd_path,
        category="Attribute",
        data_type="string",
        pii=False,
        sources=[{
            "tier": "PRIMARY",
            "locator": f"{connector} | raw | RESP",
            "path": field_path,
        }],
        transform=None,
        construction=None,
    )


def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C225334", "is_credential": False, "parse_strategy": "raw_json"},
            {"code": "C238743", "is_credential": False, "parse_strategy": "gds_envelope_json"},
            {"code": "C103403", "is_credential": False, "parse_strategy": "pygdsa_json"},
        ],
        "pii": {"fields": [], "extra_columns_scan": {"enabled": False, "patterns": []}},
        "validation": {"hard_quarantine_rules": [], "soft_warn_rules": [], "client_params": {}},
    }


# ---------------------------------------------------------------------------
# TC-1: extra_columns.* sdd_path → written to rec.extra_columns, not rec.record
# ---------------------------------------------------------------------------
class TestExtraColumnsRouting:
    def test_value_written_to_extra_columns_not_record(self):
        sf = _make_sf("C225334", "RESP", {"DerivedApplicationRecord": [{"Payload": '{"x": 1}'}]})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _ec_row(
                "SOC_derived_application",
                "C225334",
                "DerivedApplicationRecord.0.Payload",
                transform="json_double_parse",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        # Value must be in rec.extra_columns
        assert rec.extra_columns.get("SOC_derived_application") == {"x": 1}

    def test_value_not_in_rec_record(self):
        sf = _make_sf("C225334", "RESP", {"DerivedApplicationRecord": [{"Payload": '{"x": 1}'}]})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _ec_row(
                "SOC_derived_application",
                "C225334",
                "DerivedApplicationRecord.0.Payload",
                transform="json_double_parse",
            )
        ]
        apply_mapping(rec, mapping, _cfg())
        # Must NOT be at rec.record root or anywhere inside rec.record
        assert "extra_columns" not in rec.record
        assert "SOC_derived_application" not in rec.record

    def test_nested_extra_columns_path_routed(self):
        """sdd_path='extra_columns.SOC_attrs.fieldA' routes to rec.extra_columns['SOC_attrs']['fieldA']."""
        sf = _make_sf("C225334", "RESP", {"record": {"someField": "value_a"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        row = MappingRow(
            sdd_path="extra_columns.SOC_attrs.fieldA",
            category="ExtraColumn",
            data_type="string",
            pii=False,
            sources=[{"tier": "PRIMARY", "locator": "C225334 | raw | RESP",
                      "path": "record.someField"}],
            transform=None,
            construction=None,
        )
        apply_mapping(rec, [row], _cfg())
        assert rec.extra_columns.get("SOC_attrs", {}).get("fieldA") == "value_a"


# ---------------------------------------------------------------------------
# TC-2: All four group names writable to rec.extra_columns
# ---------------------------------------------------------------------------
class TestAllGroupsWritable:
    def _make_mapping_for_groups(self):
        groups = {
            "SOC_pygdsa_attributes": ("C103403", "attrs.field"),
            "SOC_derived_application": ("C225334", "DerivedApplicationRecord.0.Payload"),
            "SOC_decision_variable": ("C225334", "DecisionVariableRecord.0.Payload"),
            "SOC_decision_req": ("C238743", "data.Decision.field"),
        }
        payloads = {
            "C225334": {
                "DerivedApplicationRecord": [{"Payload": "derived_value"}],
                "DecisionVariableRecord": [{"Payload": "variable_value"}],
            },
            "C103403": {"attrs": {"field": "pygdsa_value"}},
            "C238743": {"Decision": {"decision": "APPROVED"}, "data": {"Decision": {"field": "req_value"}}},
        }
        return groups, payloads

    def test_soc_pygdsa_attributes_writable(self):
        sf = _make_sf("C103403", "RESP", {"attrs": {"field": "pygdsa_value"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        row = MappingRow(
            sdd_path="extra_columns.SOC_pygdsa_attributes",
            category="ExtraColumn", data_type="object", pii=False,
            sources=[{"tier": "PRIMARY", "locator": "C103403 | raw | RESP",
                      "path": "attrs.field"}],
            transform=None, construction=None,
        )
        apply_mapping(rec, [row], _cfg())
        assert rec.extra_columns.get("SOC_pygdsa_attributes") == "pygdsa_value"

    def test_soc_decision_req_writable(self):
        sf = _make_sf("C238743", "REQ", {"data": {"Decision": {"field": "req_value"}}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        row = MappingRow(
            sdd_path="extra_columns.SOC_decision_req",
            category="ExtraColumn", data_type="object", pii=False,
            sources=[{"tier": "PRIMARY", "locator": "C238743 | raw | REQ",
                      "path": "data.Decision.field"}],
            transform=None, construction=None,
        )
        apply_mapping(rec, [row], _cfg())
        assert rec.extra_columns.get("SOC_decision_req") == "req_value"


# ---------------------------------------------------------------------------
# TC-3: rec.record root has no extra_columns key
# ---------------------------------------------------------------------------
class TestRecordRootClean:
    def test_record_root_has_no_extra_columns_key(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _std_row("system.application.scores.score1", "C225334", "record.FICO"),
            _ec_row("SOC_derived_application", "C225334", "record.FICO"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert "extra_columns" not in rec.record
        assert "SOC_derived_application" not in rec.record

    def test_record_root_keys_are_only_expected(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "680"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _std_row("system.application.scores.score1", "C225334", "record.FICO"),
        ]
        apply_mapping(rec, mapping, _cfg())
        allowed_root_keys = {"system", "bureauData"}
        unexpected = set(rec.record.keys()) - allowed_root_keys
        assert not unexpected, f"Unexpected rec.record root keys: {unexpected}"


# ---------------------------------------------------------------------------
# TC-4: Both YAML configs have all four extra_columns_groups registered
# ---------------------------------------------------------------------------
class TestYamlGroupRegistration:
    _EXPECTED_GROUPS = {
        "SOC_pygdsa_attributes",
        "SOC_derived_application",
        "SOC_decision_variable",
        "SOC_decision_req",
    }

    def _load_group_names(self, path: str) -> set:
        cfg = yaml.safe_load(open(path))
        return {g["name"] for g in cfg.get("extra_columns_groups", [])}

    def test_usa_config_has_all_groups(self):
        names = self._load_group_names("assets/client_config.SOC_USA.yaml")
        assert self._EXPECTED_GROUPS <= names

    def test_can_config_has_all_groups(self):
        names = self._load_group_names("assets/client_config.SOC_CAN.yaml")
        assert self._EXPECTED_GROUPS <= names

    def test_usa_group_connectors_registered(self):
        cfg = yaml.safe_load(open("assets/client_config.SOC_USA.yaml"))
        groups = {g["name"]: g for g in cfg.get("extra_columns_groups", [])}
        assert groups["SOC_pygdsa_attributes"]["connector"] == "C103403"
        assert groups["SOC_derived_application"]["connector"] == "C225334"
        assert groups["SOC_decision_req"]["connector"] == "C238743"


# ---------------------------------------------------------------------------
# TC-5: Normal MappingRow (no extra_columns prefix) still writes to rec.record
# ---------------------------------------------------------------------------
class TestNormalRowUnchanged:
    def test_standard_row_writes_to_record(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "720"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _std_row("system.application.scores.score1", "C225334", "record.FICO"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert _get_path(rec.record, "system.application.scores.score1") == "720"
        assert not rec.extra_columns

    def test_standard_row_not_in_extra_columns(self):
        sf = _make_sf("C225334", "RESP", {"record": {"FICO": "720"}})
        dec_sf = _make_sf("C238743", "RESP", {"Decision": {"decision": "APPROVED"}})
        rec = _make_rec(sf, dec_sf)
        mapping = [
            _std_row("system.application.scores.score1", "C225334", "record.FICO"),
        ]
        apply_mapping(rec, mapping, _cfg())
        assert "system" not in rec.extra_columns
