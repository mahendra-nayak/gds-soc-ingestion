"""
scripts/ingest_lib.py — SOC Ingestion Pipeline Engine
Standard Schema v1.1 · Python 3.11+

Single authoritative engine file. Extend; do not fork.
All invariants from docs/INVARIANTS.md are enforced here.
"""

from __future__ import annotations

import ast
import base64
import json
import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

import xmltodict
import yaml


# ---------------------------------------------------------------------------
# AppRecord — canonical in-memory record for one Application ID
# IC-3: all ID fields stored as str at every stage; no numeric cast.
# ---------------------------------------------------------------------------

@dataclass
class AppRecord:
    app_id_canonical: str          # normalised ID (str — IC-3)
    app_id_raw: str                # original ID incl. _test suffix (str — IC-3)
    debtor_number: str             # str — IC-3
    sequence_id: str               # str — IC-3
    client_code: str               # SOC_USA | SOC_CAN
    extra_columns: dict[str, Any] = field(default_factory=dict)
    lineage: dict[str, Any]       = field(default_factory=dict)
    data: dict[str, Any]          = field(default_factory=dict)
    _pii_tokenised: bool           = field(default=False, repr=False)
    _validated: bool               = field(default=False, repr=False)
    data_lake_flag: str            = "N"


# ---------------------------------------------------------------------------
# Strategy registry
# ---------------------------------------------------------------------------

_STRATEGIES: dict[str, Any] = {}


def strategy(name: str):
    """Decorator that registers a parse strategy by name."""
    def decorator(fn):
        _STRATEGIES[name] = fn
        return fn
    return decorator


def get_strategy(name: str):
    if name not in _STRATEGIES:
        raise KeyError(
            f"Unknown parse strategy: {name!r}. Registered: {list(_STRATEGIES)}"
        )
    return _STRATEGIES[name]


# ---------------------------------------------------------------------------
# IC-1 — Credential scrub (regex/pattern-based; never exact-string matching)
# Must execute to completion on every file before any parse, log, or route.
# Connectors in scope: C161653 (Auth header), C754889 (user/pass), C103403 (Bearer)
# ---------------------------------------------------------------------------

_CREDENTIAL_PATTERNS: list[tuple[re.Pattern, str]] = [
    # HTTP Authorization header — C161653
    (re.compile(r'(?i)(Authorization\s*:\s*)\S+'), r'\g<1>[REDACTED]'),
    # username / password fields — C754889
    (re.compile(r'(?i)("?password"?\s*[=:]\s*")[^"]+("?)'), r'\g<1>[REDACTED]\g<2>'),
    (re.compile(r'(?i)("?username"?\s*[=:]\s*")[^"]+("?)'), r'\g<1>[REDACTED]\g<2>'),
    (re.compile(r'(?i)(password\s*=\s*)\S+'), r'\g<1>[REDACTED]'),
    # Bearer token — header and JSON body — C103403
    (re.compile(r'(?i)(Bearer\s+)\S+'), r'\g<1>[REDACTED]'),
    (re.compile(r'(?i)("?(?:access_token|bearer_token|api_key|client_secret)"?\s*:\s*")[^"]+("?)'), r'\g<1>[REDACTED]\g<2>'),
    # Generic token / OAuth patterns
    (re.compile(r'(?i)("?(?:token|oauth_token|refresh_token)"?\s*:\s*")[^"]{8,}("?)'), r'\g<1>[REDACTED]\g<2>'),
]


def scrub_credentials(raw_text: str) -> str:
    """
    IC-1: Pattern-based credential scrub on raw file text.
    Executes to completion before any parse, log, or downstream route.
    Returns scrubbed text. No credential value may survive in any form.
    """
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        raw_text = pattern.sub(replacement, raw_text)
    return raw_text


def scrub_credentials_struct(node: Any) -> Any:
    """Recursively scrub credentials from an already-parsed structure."""
    if isinstance(node, dict):
        return {k: scrub_credentials_struct(v) for k, v in node.items()}
    if isinstance(node, list):
        return [scrub_credentials_struct(item) for item in node]
    if isinstance(node, str):
        return scrub_credentials(node)
    return node


# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class PiiDetectedError(RuntimeError):
    """Raised by assert_no_raw_pii() when raw PII is found. Blocks DataLake write."""


class CredentialError(RuntimeError):
    """Raised when a raw credential is detected in an unsafe context."""


# ---------------------------------------------------------------------------
# PII handling — IC-2 & IC-5
# ---------------------------------------------------------------------------

# Static field inventory — supplemented by client_config pii.fields at runtime.
_PII_FIELD_NAMES: frozenset[str] = frozenset({
    "ssn", "sin", "full_name", "first_name", "last_name",
    "date_of_birth", "dob", "address", "street", "city",
    "postal_code", "zip_code", "phone", "phone_number",
    "email", "email_address",
})

# Pattern-based PII detection for extra_columns value scan (IC-2: values, not names)
_PII_VALUE_PATTERNS: list[re.Pattern] = [
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),                                  # SSN
    re.compile(r'\b\d{3}\s\d{3}\s\d{3}\b'),                                 # SIN
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b'),     # email
    re.compile(r'\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]\d{3}[-.\s]\d{4}\b'),  # phone
]

_TOKEN_PREFIX = "TOK_"


def _generate_token(value: str) -> str:
    """Produce a stable opaque token from a PII value."""
    return f"{_TOKEN_PREFIX}{uuid.uuid5(uuid.NAMESPACE_OID, value)}"


def _scan_extra_columns_for_pii(extra_columns: dict[str, Any]) -> list[str]:
    """
    IC-2: Scan extra_columns values (not field names) for raw PII patterns.
    Returns list of offending column names.
    """
    offenders: list[str] = []
    for col_name, col_value in extra_columns.items():
        str_val = str(col_value) if not isinstance(col_value, str) else col_value
        for pattern in _PII_VALUE_PATTERNS:
            if pattern.search(str_val):
                offenders.append(col_name)
                break
    return offenders


def tokenise_pii(record: AppRecord, pii_fields: list[str] | None = None) -> AppRecord:
    """
    IC-2: Replace raw PII in record.data and record.extra_columns with tokens.
    pii_fields: from client_config pii.fields; merged with built-in _PII_FIELD_NAMES.
    Sets record._pii_tokenised = True on completion.
    """
    all_pii_fields = _PII_FIELD_NAMES | set(f.lower() for f in (pii_fields or []))

    for field_name in list(record.data.keys()):
        if field_name.lower() in all_pii_fields:
            val = record.data[field_name]
            if isinstance(val, str) and val and not val.startswith(_TOKEN_PREFIX):
                record.data[field_name] = _generate_token(val)

    for col_name in list(record.extra_columns.keys()):
        if col_name.lower() in all_pii_fields:
            val = record.extra_columns[col_name]
            if isinstance(val, str) and val and not val.startswith(_TOKEN_PREFIX):
                record.extra_columns[col_name] = _generate_token(val)

    record._pii_tokenised = True
    return record


def assert_no_raw_pii(record: AppRecord) -> None:
    """
    IC-2: Write gate — raises PiiDetectedError if raw PII survives.
    (1) Pattern-scan of extra_columns values.
    (2) Known-field check in record.data.
    Must be called before write_record(). Never used as a logging step.
    """
    offenders = _scan_extra_columns_for_pii(record.extra_columns)
    if offenders:
        raise PiiDetectedError(
            f"Raw PII in extra_columns for app_id={record.app_id_canonical!r}: "
            f"columns={offenders}"
        )
    for field_name, val in record.data.items():
        if field_name.lower() in _PII_FIELD_NAMES:
            if isinstance(val, str) and val and not val.startswith(_TOKEN_PREFIX):
                raise PiiDetectedError(
                    f"Raw PII in data[{field_name!r}] for "
                    f"app_id={record.app_id_canonical!r}"
                )


# ---------------------------------------------------------------------------
# Validation — Standard Schema v1.1
# ---------------------------------------------------------------------------

_REQUIRED_RECORD_FIELDS = (
    "app_id_canonical", "app_id_raw", "debtor_number", "sequence_id", "client_code",
)


def validate(record: AppRecord) -> AppRecord:
    """
    Validate AppRecord against Standard Schema v1.1.
    IC-3: asserts all ID fields are str.
    IC-2: lineage must contain both app_id_raw and app_id_canonical.
    Sets record._validated = True on success; raises ValueError on failure.
    """
    for attr in _REQUIRED_RECORD_FIELDS:
        val = getattr(record, attr, None)
        if not val:
            raise ValueError(f"Missing required field {attr!r} on AppRecord")
        if attr in ("app_id_canonical", "app_id_raw", "debtor_number", "sequence_id"):
            if not isinstance(val, str):
                raise ValueError(
                    f"IC-3 violation: {attr!r} must be str, got {type(val).__name__}"
                )
    if "app_id_raw" not in record.lineage:
        raise ValueError("IC-3: lineage missing app_id_raw")
    if "app_id_canonical" not in record.lineage:
        raise ValueError("IC-3: lineage missing app_id_canonical")

    record._validated = True
    return record


# ---------------------------------------------------------------------------
# DataLake write — IC-2 gate (tokenise_pii + validate must precede)
# ---------------------------------------------------------------------------

def write_record(record: AppRecord, sink=None) -> dict[str, Any]:
    """
    Write a validated, PII-clean record to DataLake.

    IC-2: raises RuntimeError if tokenise_pii() or validate() not yet completed.
    IC-4: no credential value may appear in the output.
    IC-5: no raw PII may appear in DataLake=Y output.
    """
    if not record._pii_tokenised:
        raise RuntimeError(
            f"IC-2 violation: tokenise_pii() not completed for "
            f"app_id={record.app_id_canonical!r}. write_record() blocked."
        )
    if not record._validated:
        raise RuntimeError(
            f"IC-2 violation: validate() not completed for "
            f"app_id={record.app_id_canonical!r}. write_record() blocked."
        )

    assert_no_raw_pii(record)  # IC-2 write gate — not a logging step

    output: dict[str, Any] = {
        "app_id_canonical": record.app_id_canonical,   # str — IC-3
        "app_id_raw":       record.app_id_raw,         # str — IC-3
        "debtor_number":    record.debtor_number,      # str — IC-3
        "sequence_id":      record.sequence_id,        # str — IC-3
        "client_code":      record.client_code,
        "data":             record.data,
        "extra_columns":    record.extra_columns,
        "lineage":          record.lineage,
        "data_lake_flag":   "Y",
        "written_at_utc":   datetime.now(timezone.utc).isoformat(),
    }

    if sink is not None:
        sink.write(output)

    record.data_lake_flag = "Y"
    return output


# ---------------------------------------------------------------------------
# Parse strategies
# ---------------------------------------------------------------------------

@strategy("gds_envelope_json")
def _parse_gds_envelope_json(scrubbed_text: str, context: dict | None = None) -> dict:
    """Parse GDS envelope JSON; unwrap outer envelope key."""
    payload = json.loads(scrubbed_text)
    for envelope_key in ("payload", "data", "body", "content"):
        if envelope_key in payload:
            return payload[envelope_key]
    return payload


@strategy("raw_json")
def _parse_raw_json(scrubbed_text: str, context: dict | None = None) -> dict:
    """Parse raw JSON with no envelope stripping."""
    return json.loads(scrubbed_text)


@strategy("xml_dict")
def _parse_xml_dict(scrubbed_text: str, context: dict | None = None) -> dict:
    """Parse XML into a dict via xmltodict."""
    return xmltodict.parse(scrubbed_text)


@strategy("soap_xml")
def _parse_soap_xml(scrubbed_text: str, context: dict | None = None) -> dict:
    """Parse SOAP XML; unwrap Envelope > Body > first child."""
    parsed = xmltodict.parse(scrubbed_text)
    envelope = (
        parsed.get("soap:Envelope")
        or parsed.get("Envelope")
        or parsed
    )
    body = (
        envelope.get("soap:Body")
        or envelope.get("Body")
        or envelope
    )
    for val in body.values():
        if val is not None:
            return val if isinstance(val, dict) else {"value": val}
    return body


@strategy("fff")
def _parse_fff(scrubbed_text: str, context: dict | None = None) -> dict:
    # TODO(Q-FFF): FFF parse strategy body not implemented.
    # Implementation is gated on Q-FFF resolution.
    raise NotImplementedError(
        "TODO(Q-FFF): FFF parser is not implemented. "
        "Implementation is gated on Q-FFF resolution."
    )


@strategy("binary_external_ref")
def _parse_binary_external_ref(scrubbed_text: str, context: dict | None = None) -> dict:
    """Binary files produce an external reference stub; content is not parsed inline."""
    return {
        "binary_external_ref": True,
        "content_preview": scrubbed_text[:64] if scrubbed_text else "",
        "note": "Binary file — handled by external reference adapter.",
    }


@strategy("credential_discard")
def _parse_credential_discard(scrubbed_text: str, context: dict | None = None) -> dict:
    """
    Files classified as credential-only are discarded post-scrub.
    IC-1/IC-4: no credential content is parsed, logged, or stored.
    """
    return {"discarded": True, "reason": "credential_discard strategy applied"}


# ---------------------------------------------------------------------------
# Transform dispatch
# ---------------------------------------------------------------------------

def apply_transform(transform_name: str, value: Any, params: dict | None = None) -> Any:
    """
    Dispatch a named transform. Raises KeyError for unknown names.
    eval() is prohibited — ast.literal_eval() is used exclusively (CLAUDE.md).
    """
    params = params or {}
    _dispatch = {
        "date_to_utc_iso":   _transform_date_to_utc_iso,
        "string_to_numeric": _transform_string_to_numeric,
        "split_on_delim":    _transform_split_on_delim,
        "json_double_parse": _transform_json_double_parse,
        "ast_literal_eval":  _transform_ast_literal_eval,
        "base64_extract":    _transform_base64_extract,
    }
    if transform_name not in _dispatch:
        raise KeyError(
            f"Unknown transform: {transform_name!r}. Registered: {list(_dispatch)}"
        )
    return _dispatch[transform_name](value, params)


def _transform_date_to_utc_iso(value: Any, params: dict) -> str:
    fmt = params.get("fmt", "%Y-%m-%d")
    dt = datetime.strptime(str(value), fmt)
    return dt.replace(tzinfo=timezone.utc).isoformat()


def _transform_string_to_numeric(value: Any, params: dict) -> int | float:
    numeric_type = params.get("numeric_type", "float")
    return int(str(value).strip()) if numeric_type == "int" else float(str(value).strip())


def _transform_split_on_delim(value: Any, params: dict) -> list[str]:
    delim = params.get("delim", ",")
    return [part.strip() for part in str(value).split(delim)]


def _transform_json_double_parse(value: Any, params: dict) -> Any:
    first = json.loads(value) if isinstance(value, str) else value
    return json.loads(first) if isinstance(first, str) else first


def _transform_ast_literal_eval(value: Any, params: dict) -> Any:
    # eval() is prohibited — ast.literal_eval() exclusively (CLAUDE.md)
    return ast.literal_eval(str(value))


def _transform_base64_extract(value: Any, params: dict) -> str:
    encoding = params.get("encoding", "utf-8")
    return base64.b64decode(str(value)).decode(encoding)


# ---------------------------------------------------------------------------
# Lineage and ID helpers
# ---------------------------------------------------------------------------

def build_lineage(
    app_id_raw: str,
    app_id_canonical: str,
    source_file: str,
    strategy_name: str,
    client_code: str,
) -> dict[str, str]:
    """
    Build lineage dict. IC-3: both app_id_raw and app_id_canonical must be present.
    """
    return {
        "app_id_raw":       str(app_id_raw),         # str — IC-3
        "app_id_canonical": str(app_id_canonical),   # str — IC-3
        "source_file":      source_file,
        "parse_strategy":   strategy_name,
        "client_code":      client_code,
        "pipeline_version": "v1.1",
        "processed_at_utc": datetime.now(timezone.utc).isoformat(),
    }


def normalise_app_id(raw_id: str) -> str:
    """
    Produce app_id_canonical from app_id_raw.
    Strips _test suffix; preserves leading zeros. Always returns str (IC-3).
    """
    return str(raw_id).removesuffix("_test").strip()


# ---------------------------------------------------------------------------
# Pipeline entry point
# ---------------------------------------------------------------------------

def run_pipeline(
    manifest: list[dict],
    client_config: dict,
    sink=None,
) -> list[dict]:
    """
    Process a file manifest through the full SOC ingestion pipeline.

    Pipeline order (invariants enforced):
      1. scrub_credentials()   — IC-1: before any parse/log/route
      2. parse via strategy
      3. build AppRecord       — IC-3: IDs as str
      4. tokenise_pii()        — IC-2
      5. validate()            — IC-2
      6. write_record()        — IC-2 gate + assert_no_raw_pii() inside
                                 IC-4: no credential in output
                                 IC-5: no raw PII in DataLake=Y output

    Returns list of DataLake output dicts for successfully written records.
    """
    results: list[dict] = []
    pii_fields: list[str] = client_config.get("pii", {}).get("fields", [])

    for entry in manifest:
        raw_text: str = entry.get("raw_text", "")
        strategy_name: str = entry.get("parse_strategy", "raw_json")
        app_id_raw: str = str(entry.get("app_id_raw", ""))        # str — IC-3
        app_id_canonical: str = normalise_app_id(app_id_raw)      # str — IC-3
        debtor_number: str = str(entry.get("debtor_number", ""))  # str — IC-3
        sequence_id: str = str(entry.get("sequence_id", ""))      # str — IC-3
        client_code: str = client_config.get("client_code", "")
        source_file: str = entry.get("source_file", "")

        # Step 1 — IC-1: scrub credentials before any parse or log
        scrubbed = scrub_credentials(raw_text)

        # Step 2 — parse
        parse_fn = get_strategy(strategy_name)
        parsed = parse_fn(scrubbed)

        # Step 3 — build AppRecord (IDs always str — IC-3)
        record = AppRecord(
            app_id_canonical=app_id_canonical,
            app_id_raw=app_id_raw,
            debtor_number=debtor_number,
            sequence_id=sequence_id,
            client_code=client_code,
            data=parsed if isinstance(parsed, dict) else {"content": parsed},
            lineage=build_lineage(
                app_id_raw, app_id_canonical, source_file, strategy_name, client_code
            ),
        )

        # Step 4 — IC-2: tokenise PII before write
        record = tokenise_pii(record, pii_fields=pii_fields)

        # Step 5 — IC-2: validate (checks IC-3 lineage completeness)
        record = validate(record)

        # Step 6 — IC-2 write gate; assert_no_raw_pii() called inside write_record()
        output = write_record(record, sink=sink)
        results.append(output)

    return results
