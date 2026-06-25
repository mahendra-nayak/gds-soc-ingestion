"""
tests/unit/test_parse_xml.py — TASK-4.2
Unit tests for xml_dict parse strategy (C1677939 TransUnion USA).

Strategy: HTTP envelope strip → maybe_gunzip → xmltodict.parse → _strip_ns()

Invariants verified:
  _strip_ns() is recursive — TODO(production-hardening) comment present in engine.
  Malformed XML propagates xml.parsers.expat.ExpatError without swallowing.

TC-1: XML with ns2: namespace prefixes → all prefixes stripped at top level
TC-2: Deeply nested namespaces (ns2:/bs:/cs:) → all levels stripped recursively
TC-3: Malformed XML → xml.parsers.expat.ExpatError propagated

Fixture: tests/fixtures/transunion_sample.xml (synthetic; namespace prefixes ns2:, bs:, cs:)
"""
from pathlib import Path
from xml.parsers.expat import ExpatError

import pytest

from scripts.ingest_lib import SourceFile, _strip_ns, parse_file

FIXTURES = Path(__file__).parent.parent / "fixtures"
TRANSUNION_XML = FIXTURES / "transunion_sample.xml"


# ---------------------------------------------------------------------------
# Config stub — C1677939 registered with xml_dict strategy
# ---------------------------------------------------------------------------
def _cfg() -> dict:
    return {
        "client": {"code": "SOC_USA", "schema_version": "1.1"},
        "connectors": [
            {"code": "C1677939", "parse_strategy": "xml_dict", "is_credential": False},
        ],
    }


def _make_sf(path: Path, connector: str = "C1677939") -> SourceFile:
    return SourceFile(
        path=path,
        folder="data",
        connector=connector,
        direction="RESP",
        step=None,
        app_id_raw="500249960_20250101000000",
        sequence_id="1",
    )


# ---------------------------------------------------------------------------
# TC-1: XML with ns2: prefixes → prefixes stripped at top level
# ---------------------------------------------------------------------------
class TestNs2PrefixStripping:
    """Uses tests/fixtures/transunion_sample.xml — ns2:, bs:, cs: prefixes."""

    def test_top_level_key_has_no_ns_prefix(self):
        sf = _make_sf(TRANSUNION_XML)
        result = parse_file(sf, _cfg())
        assert "CreditBureau" in result, (
            f"Expected 'CreditBureau' (ns2: stripped); got keys: {list(result)}"
        )

    def test_ns2_prefix_not_present_in_top_key(self):
        sf = _make_sf(TRANSUNION_XML)
        result = parse_file(sf, _cfg())
        for key in result:
            assert ":" not in key, f"Namespace prefix not stripped from key: {key!r}"

    def test_header_child_keys_stripped(self):
        sf = _make_sf(TRANSUNION_XML)
        result = parse_file(sf, _cfg())
        header = result["CreditBureau"]["Header"]
        assert "RequestId" in header, f"bs: not stripped from Header; keys: {list(header)}"
        assert "ReportDate" in header

    def test_payload_set_on_source_file(self):
        sf = _make_sf(TRANSUNION_XML)
        parse_file(sf, _cfg())
        assert sf.payload is not None
        assert "CreditBureau" in sf.payload


# ---------------------------------------------------------------------------
# TC-2: Deeply nested namespaces → all levels stripped recursively
# ---------------------------------------------------------------------------
class TestNestedNamespaceStripping:
    """Inline synthetic XML; verifies _strip_ns() recurses through all levels."""

    def _write_xml(self, tmp_path: Path, content: bytes) -> Path:
        f = tmp_path / "nested.xml"
        f.write_bytes(content)
        return f

    def test_three_levels_of_ns_all_stripped(self, tmp_path):
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ns2:Root xmlns:ns2="urn:a" xmlns:bs="urn:b" xmlns:cs="urn:c">'
            b'  <bs:Middle>'
            b'    <cs:Leaf>value</cs:Leaf>'
            b'  </bs:Middle>'
            b'</ns2:Root>'
        )
        f = self._write_xml(tmp_path, xml)
        sf = _make_sf(f)
        result = parse_file(sf, _cfg())
        assert "Root" in result
        assert "Middle" in result["Root"]
        assert "Leaf" in result["Root"]["Middle"]

    def test_no_colon_in_any_key_after_strip(self, tmp_path):
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ns2:A xmlns:ns2="urn:a" xmlns:bs="urn:b">'
            b'  <bs:B><ns2:C>x</ns2:C></bs:B>'
            b'</ns2:A>'
        )
        f = self._write_xml(tmp_path, xml)
        sf = _make_sf(f)
        result = parse_file(sf, _cfg())

        def _all_keys(d):
            if isinstance(d, dict):
                for k, v in d.items():
                    yield k
                    yield from _all_keys(v)
            elif isinstance(d, list):
                for item in d:
                    yield from _all_keys(item)

        for key in _all_keys(result):
            assert ":" not in key, f"Namespace prefix not stripped: {key!r}"

    def test_list_children_each_stripped(self, tmp_path):
        """Sibling elements with namespace prefixes produce a list; each stripped."""
        xml = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ns2:Items xmlns:ns2="urn:a">'
            b'  <ns2:Item><ns2:Val>1</ns2:Val></ns2:Item>'
            b'  <ns2:Item><ns2:Val>2</ns2:Val></ns2:Item>'
            b'</ns2:Items>'
        )
        f = self._write_xml(tmp_path, xml)
        sf = _make_sf(f)
        result = parse_file(sf, _cfg())
        items = result["Items"]["Item"]
        assert isinstance(items, list), "Repeated elements must produce a list"
        for item in items:
            assert "Val" in item
            assert not any(":" in k for k in item)

    def test_strip_ns_unit_nested_dict(self):
        """Direct unit test of _strip_ns with a hand-crafted nested dict."""
        raw = {
            "ns2:Root": {
                "bs:Child": {
                    "cs:Leaf": "data",
                    "cs:Count": "3",
                },
                "@xmlns:ns2": "urn:a",
            }
        }
        result = _strip_ns(raw)
        assert "Root" in result
        assert "Child" in result["Root"]
        assert "Leaf" in result["Root"]["Child"]
        assert result["Root"]["Child"]["Leaf"] == "data"


# ---------------------------------------------------------------------------
# TC-3: Malformed XML → ExpatError propagated
# ---------------------------------------------------------------------------
class TestMalformedXml:
    def test_unclosed_tag_raises_expat_error(self, tmp_path):
        f = tmp_path / "bad.xml"
        f.write_bytes(b"<Root><Unclosed>")
        sf = _make_sf(f)
        with pytest.raises(ExpatError):
            parse_file(sf, _cfg())

    def test_invalid_characters_raises_expat_error(self, tmp_path):
        f = tmp_path / "chars.xml"
        f.write_bytes(b"<<not xml at all>>")
        sf = _make_sf(f)
        with pytest.raises(ExpatError):
            parse_file(sf, _cfg())

    def test_empty_file_raises_expat_error(self, tmp_path):
        f = tmp_path / "empty.xml"
        f.write_bytes(b"")
        sf = _make_sf(f)
        with pytest.raises(ExpatError):
            parse_file(sf, _cfg())


# ---------------------------------------------------------------------------
# Structural check: TODO(production-hardening) comment present in engine
# ---------------------------------------------------------------------------
class TestProductionHardeningTodo:
    def test_strip_ns_has_depth_guard_todo(self):
        """Verify the production-hardening TODO comment exists in the engine source."""
        engine = Path(__file__).parent.parent.parent / "scripts" / "ingest_lib.py"
        source = engine.read_text(encoding="utf-8")
        assert "TODO(production-hardening)" in source, (
            "_strip_ns() must carry TODO(production-hardening) depth guard comment"
        )
