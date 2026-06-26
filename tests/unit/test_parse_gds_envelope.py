"""
tests/unit/test_parse_gds_envelope.py — TASK-4.1
Unit tests for gds_envelope_json parse strategy.

Strategy: obj.get('data', obj) — returns inner data{} when present, else full object.

Invariants verified:
  D-04: When parsing C238743-RESP, the strategy must not extract or pre-populate
        any decision field on the AppRecord. Decision extraction is deferred to
        TASK-5.2 / apply_mapping().

TC-1: GDS envelope with data{} key → inner data{} contents returned
TC-2: GDS envelope without data{} key → full object returned
TC-3: Malformed JSON → json.JSONDecodeError propagated
TC-4: C238743-RESP parsed → rec.record['decision'] is NOT set by this function (D-04)
"""
import json

import pytest

from scripts.ingest_lib import AppRecord, SourceFile, parse_file


# ---------------------------------------------------------------------------
# Config stub — minimal, with C238743 registered for gds_envelope_json
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C78098",   "parse_strategy": "gds_envelope_json", "is_credential": False},
            {"code": "C78449",   "parse_strategy": "gds_envelope_json", "is_credential": False},
            {"code": "C215125",  "parse_strategy": "gds_envelope_json", "is_credential": False},
            {"code": "C238743",  "parse_strategy": "gds_envelope_json", "is_credential": False},
            {"code": "C224847",  "parse_strategy": "gds_envelope_json", "is_credential": False},
        ],
    }


def _make_sf(path, connector: str = "C78098", direction: str = "RESP") -> SourceFile:
    return SourceFile(
        path=path,
        folder="data",
        connector=connector,
        direction=direction,
        step=None,
        app_id_raw="500249960_20250101000000",
        sequence_id="1",
    )


# ---------------------------------------------------------------------------
# TC-1: Envelope with data{} → inner contents returned
# ---------------------------------------------------------------------------
class TestWithDataKey:
    def test_data_contents_returned(self, tmp_path):
        inner = {"score": 720, "bureau": "EFX"}
        envelope = {"meta": {"source": "GDS"}, "data": inner}
        f = tmp_path / "c78098_resp.json"
        f.write_text(json.dumps(envelope), encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        result = parse_file(sf, _cfg())
        assert result == inner

    def test_data_key_not_in_result(self, tmp_path):
        """The wrapping 'meta' key must not bleed into the returned object."""
        envelope = {"meta": {"source": "GDS"}, "data": {"score": 750}}
        f = tmp_path / "c78449_resp.json"
        f.write_text(json.dumps(envelope), encoding="utf-8")
        sf = _make_sf(f, connector="C78449")
        result = parse_file(sf, _cfg())
        assert "meta" not in result

    def test_payload_set_on_source_file(self, tmp_path):
        inner = {"approved": True}
        f = tmp_path / "c215125_resp.json"
        f.write_text(json.dumps({"data": inner}), encoding="utf-8")
        sf = _make_sf(f, connector="C215125")
        parse_file(sf, _cfg())
        assert sf.payload == inner


# ---------------------------------------------------------------------------
# TC-2: Envelope without data{} → full object returned
# ---------------------------------------------------------------------------
class TestWithoutDataKey:
    def test_full_object_returned_when_no_data_key(self, tmp_path):
        obj = {"score": 680, "bureau": "TU", "status": "completed"}
        f = tmp_path / "c224847_resp.json"
        f.write_text(json.dumps(obj), encoding="utf-8")
        sf = _make_sf(f, connector="C224847")
        result = parse_file(sf, _cfg())
        assert result == obj

    def test_all_keys_present_when_no_data_key(self, tmp_path):
        obj = {"a": 1, "b": 2, "c": 3}
        f = tmp_path / "c78098_ndata.json"
        f.write_text(json.dumps(obj), encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        result = parse_file(sf, _cfg())
        assert set(result.keys()) == {"a", "b", "c"}

    def test_empty_object_without_data_returned_as_is(self, tmp_path):
        f = tmp_path / "c78098_empty.json"
        f.write_text("{}", encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        result = parse_file(sf, _cfg())
        assert result == {}


# ---------------------------------------------------------------------------
# TC-3: Malformed JSON → json.JSONDecodeError propagated
# ---------------------------------------------------------------------------
class TestMalformedJson:
    def test_invalid_json_raises_decode_error(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("{not valid json", encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        with pytest.raises(json.JSONDecodeError):
            parse_file(sf, _cfg())

    def test_empty_file_raises_not_implemented(self, tmp_path):
        # Empty file is non-JSON — treated as FFF/unrecognised format (Q-FFF gate)
        f = tmp_path / "empty.json"
        f.write_text("", encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        with pytest.raises(NotImplementedError):
            parse_file(sf, _cfg())

    def test_truncated_json_raises_decode_error(self, tmp_path):
        f = tmp_path / "truncated.json"
        f.write_text('{"data": {"score": 700', encoding="utf-8")
        sf = _make_sf(f, connector="C78098")
        with pytest.raises(json.JSONDecodeError):
            parse_file(sf, _cfg())


# ---------------------------------------------------------------------------
# TC-4: C238743-RESP parsed → rec.record['decision'] NOT set (D-04)
# ---------------------------------------------------------------------------
class TestC238743D04Invariant:
    """D-04: gds_envelope_json must not pre-populate any decision field.
    Decision extraction is reserved for apply_mapping() / TASK-5.2.
    """

    def test_decision_not_in_record_after_parse(self, tmp_path):
        payload = {"data": {"Decision": {"decision": "APP", "interestrate": "5.5"}}}
        f = tmp_path / "c238743_resp.json"
        f.write_text(json.dumps(payload), encoding="utf-8")
        sf = _make_sf(f, connector="C238743", direction="RESP")
        rec = AppRecord(
            app_id_canonical="500249960_20250101000000",
            app_id_raw="500249960_20250101000000",
        )
        parse_file(sf, _cfg())
        assert "decision" not in rec.record, (
            "D-04: gds_envelope_json must not write decision into rec.record"
        )

    def test_payload_available_but_decision_not_extracted(self, tmp_path):
        """Parse makes payload available on sf; decision extraction is deferred."""
        inner = {"Decision": {"decision": "DEC", "interestrate": "7.0"}}
        f = tmp_path / "c238743_resp2.json"
        f.write_text(json.dumps({"data": inner}), encoding="utf-8")
        sf = _make_sf(f, connector="C238743", direction="RESP")
        rec = AppRecord(
            app_id_canonical="500249960_20250101000000",
            app_id_raw="500249960_20250101000000",
        )
        parse_file(sf, _cfg())
        # payload is accessible for later mapping stage
        assert sf.payload == inner
        # but decision has not been written anywhere on the record
        assert "decision" not in rec.record
        assert rec.record == {}

    def test_record_entirely_untouched_by_parse(self, tmp_path):
        """parse_file must not mutate the AppRecord at all — only sf.payload."""
        f = tmp_path / "c238743_resp3.json"
        f.write_text(json.dumps({"data": {"x": 1}}), encoding="utf-8")
        sf = _make_sf(f, connector="C238743", direction="RESP")
        rec = AppRecord(
            app_id_canonical="500249960_20250101000000",
            app_id_raw="500249960_20250101000000",
        )
        pre_record = dict(rec.record)
        pre_lineage = dict(rec.lineage)
        parse_file(sf, _cfg())
        assert rec.record == pre_record
        assert rec.lineage == pre_lineage
