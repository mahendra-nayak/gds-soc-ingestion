"""
tests/unit/test_double_parse.py — TASK-6.3
Unit tests for json_double_parse and ast_literal_eval transforms.

json_double_parse: value is a stringified JSON object — parse once more with json.loads().
ast_literal_eval:  value is a Python repr string — parse with ast.literal_eval().

SECURITY INVARIANT: eval() must never be called. ast.literal_eval() is the only
permitted Python-repr parsing method (CLAUDE.md IC-4 / CC must-not).

TC-1: json_double_parse — stringified JSON parsed correctly
TC-2: ast_literal_eval — Python repr dict parsed correctly
TC-3: eval() not present in engine source (static grep assertion)
TC-4: Malformed inner JSON → json.JSONDecodeError propagated
TC-5: ast.literal_eval on non-literal expression → ValueError propagated (not eval'd)
"""
import json as _json
import re
import ast as _ast

import pytest

from scripts.ingest_lib import AppRecord, MappingRow, SourceFile, apply_transform
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _make_rec() -> AppRecord:
    return AppRecord(
        app_id_canonical="500249960_20250101000000",
        app_id_raw="500249960_20250101000000",
        geography="USA",
    )


def _row(transform: str) -> MappingRow:
    return MappingRow(
        sdd_path="extra_columns.test_group",
        category="ExtraColumn",
        data_type="object",
        pii=False,
        sources=[],
        transform=transform,
        construction=None,
    )


# ---------------------------------------------------------------------------
# TC-1: json_double_parse — stringified JSON parsed correctly
# ---------------------------------------------------------------------------
class TestJsonDoubleParse:
    def test_stringified_json_object_parsed(self):
        value = '{"key": "val", "score": 720}'
        result = apply_transform(value, _row("json_double_parse"), _make_rec(), {})
        assert result == {"key": "val", "score": 720}

    def test_stringified_json_array_parsed(self):
        value = '[1, 2, 3]'
        result = apply_transform(value, _row("json_double_parse"), _make_rec(), {})
        assert result == [1, 2, 3]

    def test_nested_object_parsed(self):
        inner = {"applicant": {"firstName": "John", "age": 30}}
        value = _json.dumps(inner)
        result = apply_transform(value, _row("json_double_parse"), _make_rec(), {})
        assert result == inner

    def test_stringified_null_parsed_to_none(self):
        result = apply_transform("null", _row("json_double_parse"), _make_rec(), {})
        assert result is None

    def test_stringified_number_parsed(self):
        result = apply_transform("42", _row("json_double_parse"), _make_rec(), {})
        assert result == 42


# ---------------------------------------------------------------------------
# TC-2: ast_literal_eval — Python repr dict parsed correctly
# ---------------------------------------------------------------------------
class TestAstLiteralEval:
    def test_python_repr_dict_parsed(self):
        value = "{'key': 'val', 'score': 720}"
        result = apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})
        assert result == {"key": "val", "score": 720}

    def test_python_repr_list_parsed(self):
        value = "[1, 2, 3]"
        result = apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})
        assert result == [1, 2, 3]

    def test_python_repr_nested_parsed(self):
        value = "{'applicant': {'name': 'John', 'age': 30}}"
        result = apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})
        assert result == {"applicant": {"name": "John", "age": 30}}

    def test_python_repr_tuple_parsed(self):
        value = "(1, 2, 3)"
        result = apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})
        assert result == (1, 2, 3)


# ---------------------------------------------------------------------------
# TC-3: eval() not present in engine source (static assertion — IC-4 / CC must-not)
# ---------------------------------------------------------------------------
class TestNoBarEval:
    def test_bare_eval_not_in_engine(self):
        """Ensure eval() is never called directly in the engine.
        Only ast.literal_eval() is permitted for Python-repr parsing."""
        engine_path = Path("scripts/ingest_lib.py")
        source = engine_path.read_text(encoding="utf-8")
        # Find all occurrences of eval( that are NOT ast.literal_eval
        matches = [
            line.strip()
            for line in source.splitlines()
            if re.search(r'\beval\s*\(', line)
            and "ast.literal_eval" not in line
            and line.strip().startswith("#") is False
        ]
        assert matches == [], f"Bare eval() found in engine:\n" + "\n".join(matches)


# ---------------------------------------------------------------------------
# TC-4: Malformed inner JSON → json.JSONDecodeError propagated
# ---------------------------------------------------------------------------
class TestMalformedJson:
    def test_malformed_json_raises_decode_error(self):
        value = '{"key": invalid}'
        with pytest.raises(_json.JSONDecodeError):
            apply_transform(value, _row("json_double_parse"), _make_rec(), {})

    def test_truncated_json_raises_decode_error(self):
        value = '{"key": "val"'
        with pytest.raises(_json.JSONDecodeError):
            apply_transform(value, _row("json_double_parse"), _make_rec(), {})

    def test_empty_string_raises_decode_error(self):
        value = ""
        with pytest.raises(_json.JSONDecodeError):
            apply_transform(value, _row("json_double_parse"), _make_rec(), {})


# ---------------------------------------------------------------------------
# TC-5: ast.literal_eval on non-literal expression → ValueError propagated
# ---------------------------------------------------------------------------
class TestAstLiteralEvalSecurity:
    def test_function_call_raises_value_error(self):
        """ast.literal_eval must reject arbitrary expressions — not evaluate them."""
        value = "__import__('os').system('echo pwned')"
        with pytest.raises((ValueError, TypeError)):
            apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})

    def test_variable_reference_raises(self):
        value = "undefined_variable"
        with pytest.raises((ValueError, TypeError)):
            apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})

    def test_malformed_repr_raises(self):
        value = "{'key': }"
        with pytest.raises((ValueError, SyntaxError)):
            apply_transform(value, _row("ast_literal_eval"), _make_rec(), {})
