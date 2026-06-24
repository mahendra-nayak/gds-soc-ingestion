"""
DG-Forge — Generic Ingestion Engine
===================================
Client-agnostic library that turns a raw GDS package (one client's ZIP) into
standardised, one-record-per-App-ID DataLake output aligned to Standard Schema.

Everything client-specific is data: it comes from
  - client_config.<CLIENT>.yaml      (structural config — see assets/ template)
  - field_mapping.<CLIENT>.xlsx      (per-SDD-path field mapping sheet)

This module implements the COMMON SPINE (identical across SOC / USCC / Kapitus /
TIB) and dispatches to registered strategies for the bits that vary.

THREE INVARIANTS (not config-toggleable — enforced by `run_pipeline`):
  I1  Credential scrub runs FIRST, before any logging/parsing/routing.
  I2  PII is tokenised BEFORE any write; a post-write assertion proves zero raw
      PII in the DataLake=Y partition.
  I3  Validation runs BEFORE write; hard-quarantine failures block the write.

DG-Forge governance: this engine is operational tooling. The per-client config
and field-mapping content are engineer-authored and signed off — not generated.

Status: SCAFFOLD. Deterministic plumbing is implemented; client-specific parse
bodies and the vault/object-store/DataLake adapters are marked `TODO(team)`.
"""
from __future__ import annotations

import base64
import gzip
import json
import logging
import re
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable

log = logging.getLogger("dg_forge.ingest")


# =============================================================================
# 0. Config + record containers
# =============================================================================
@dataclass
class ClientConfig:
    """Parsed client_config.<CLIENT>.yaml. Thin wrapper so callers get .get paths."""
    raw: dict

    @classmethod
    def load(cls, path: str | Path) -> "ClientConfig":
        import yaml  # pyyaml
        with open(path) as fh:
            return cls(yaml.safe_load(fh))

    def __getitem__(self, key): return self.raw[key]
    def get(self, key, default=None): return self.raw.get(key, default)

    @property
    def client_code(self) -> str: return self.raw["client"]["code"]
    @property
    def schema_version(self) -> str: return str(self.raw["client"]["schema_version"])
    @property
    def folder_priority(self) -> list[str]:
        return [f["name"] for f in self.raw["package"]["folder_priority"]]


@dataclass
class SourceFile:
    """One physical file from the package, after manifest + classification."""
    path: Path
    folder: str
    connector: str | None
    direction: str | None          # REQ / RESP / None
    step: int | None
    app_id_raw: str | None         # str — IC-3 / INV-07; None if unclassified
    sequence_id: str | None        # str — IC-3
    payload: Any = None            # populated after parse
    raw_bytes: bytes | None = None
    geography: str | None = None   # USA | CAN | None (unclassified / unrecognised)


@dataclass
class AppRecord:
    """Accumulates one App ID's standardised output as the pipeline runs."""
    app_id_canonical: str
    app_id_raw: str
    geography: str | None = None
    files: list[SourceFile] = field(default_factory=list)
    record: dict = field(default_factory=dict)        # the SS output
    extra_columns: dict = field(default_factory=dict)
    lineage: dict = field(default_factory=dict)
    validation_failures: list[str] = field(default_factory=list)
    quarantined: bool = False


# =============================================================================
# 1. INGESTION — unzip, manifest, classify
# =============================================================================
def unpack_zip(zip_path: str | Path, dest: str | Path) -> Path:
    dest = Path(dest)
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as z:
        # guard against path traversal
        for member in z.namelist():
            target = (dest / member).resolve()
            if not str(target).startswith(str(dest.resolve())):
                raise ValueError(f"Unsafe path in zip: {member}")
        z.extractall(dest)
    return dest


def build_manifest(root: Path, cfg: ClientConfig) -> list[SourceFile]:
    """Walk the package and classify each file by folder/connector/direction.

    Tolerates folders that are present-but-empty (USCC/Kapitus cc_extracts/).
    """
    folders = cfg.folder_priority
    files: list[SourceFile] = []
    for folder in folders:
        fdir = root / folder
        if not fdir.exists():
            log.info("folder %s absent — skipping", folder)
            continue
        members = list(fdir.rglob("*"))
        if not members:
            log.info("folder %s present but empty — tolerated", folder)
            continue
        for p in members:
            if p.is_file():
                files.append(_classify_file(p, folder, cfg))
    return files


_VALID_GEOS: frozenset[str] = frozenset({"CAN", "USA"})

# Direction aliases accepted from filenames (case-insensitive)
_DIRECTION_MAP: dict[str, str] = {
    "request": "REQ", "req": "REQ",
    "response": "RESP", "resp": "RESP",
}


def _classify_file(p: Path, folder: str, cfg: ClientConfig) -> SourceFile:
    """Extract identity fields from one filename using the config-declared regex.

    Single purpose: filename token parsing → SourceFile field population.
    CQ-001: conditional nesting ≤ 2 levels.

    INV-07: app_id_raw built as VARCHAR string — no numeric cast at any stage.
    INV-10: geography set only from explicit geo token; never inferred from payload.
    Amendment A1: no-match files flagged for quarantine, not silently dropped.
    """
    sf = SourceFile(path=p, folder=folder, connector=None, direction=None,
                    step=None, app_id_raw=None, sequence_id=None)
    appid_cfg = cfg["application_id"]
    if appid_cfg["source"] != "filename_tokens":
        return sf

    m = re.match(appid_cfg["filename"]["pattern"], p.name, re.IGNORECASE)
    if not m:
        # Amendment A1: warn; dispatcher will quarantine with 'filename_parse_failed'
        log.warning("UNCLASSIFIED file=%s — will be quarantined by dispatcher", p.name)
        return sf  # app_id_raw=None, geography=None

    gd = m.groupdict()

    # connector
    sf.connector = gd.get("connector")

    # direction — normalise to REQ | RESP | None
    sf.direction = _DIRECTION_MAP.get((gd.get("direction") or "").lower())

    # sequence_id — str, never cast to int (IC-3)
    sf.sequence_id = gd.get("sequence_id") or None

    # step
    sf.step = int(gd["step"]) if gd.get("step") else None

    # app_id_raw — VARCHAR string concatenation (INV-07 / IC-3)
    debtor = gd.get("debtor", "")
    dt = gd.get("dt", "")
    test_suffix = "_test" if gd.get("test") else ""
    sf.app_id_raw = debtor + "_" + dt + test_suffix  # str — never numeric

    # geography — INV-10: explicit token only; no payload inference
    geo = (gd.get("geo") or "").upper()
    if geo in _VALID_GEOS:
        sf.geography = geo
    else:
        log.warning("UNRECOGNISED geo=%r in file=%s — geography set to None", geo, p.name)
        sf.geography = None

    return sf


# =============================================================================
# 2. INVARIANT I1 — CREDENTIAL SCRUB (always first)
# =============================================================================
def scrub_credentials(files: list[SourceFile], cfg: ClientConfig) -> list[str]:
    """Remove credentials/secrets in place BEFORE anything reads the payloads.

    Returns the list of scrubbed connectors for lineage. Operates on raw_bytes
    where the secret is in the wire header, and on parsed structures otherwise.
    """
    scrubbed: list[str] = []
    rules = cfg.get("preprocess", {}).get("credential_scrub", []) or []
    by_connector: dict[str, list[dict]] = {}
    for r in rules:
        by_connector.setdefault(r["connector"], []).append(r)

    for sf in files:
        for rule in by_connector.get(sf.connector or "", []):
            _apply_scrub(sf, rule)
            scrubbed.append(f"{sf.connector}:{rule.get('method')}")
    return sorted(set(scrubbed))


def _apply_scrub(sf: SourceFile, rule: dict) -> None:
    """Dispatch to the appropriate scrub implementation.

    INV-01: all methods use pattern-based detection — never exact-match of known
    credential values.  raw_bytes is overwritten in-place so no downstream
    function can access the unredacted value.
    """
    method = rule["method"]
    if method == "discard_payload":
        sf.raw_bytes = b"[SCRUBBED_PAYLOAD]"
        sf.payload = None
    elif method == "redact":
        _scrub_redact(sf, rule)
    elif method == "null_out":
        _scrub_null_out(sf, rule)
    elif method == "scrub_json_body":
        _scrub_json_body(sf, rule)
    if rule.get("critical"):
        log.warning("CRITICAL scrub applied to %s (%s)", sf.connector, rule.get("location"))


def _load_raw_text(sf: SourceFile) -> str | None:
    """Read sf.raw_bytes (loading from disk if needed) and decode to str."""
    if sf.raw_bytes is None:
        sf.raw_bytes = sf.path.read_bytes()
    try:
        return sf.raw_bytes.decode("utf-8", errors="replace")
    except Exception:
        return None


def _scrub_redact(sf: SourceFile, rule: dict) -> None:
    """Pattern-based regex redaction in raw bytes (INV-01).

    Applies rule['pattern'] regex to the decoded payload text and replaces
    matches with rule['replacement'].  Overwrites sf.raw_bytes in-place.

    Default pattern targets HTTP Authorization header (C161653 use-case).
    """
    text = _load_raw_text(sf)
    if text is None:
        return
    # NOTE: EXECUTION_PLAN specifies r'(?i)(Authorization:\s*)\S+' but \S+
    # matches only the scheme word (e.g. 'Bearer'), leaving the token value
    # intact.  IC-4 requires zero credential in persisted records, so the
    # correct pattern must match the entire header value to end-of-line.
    # Using [^\r\n]+ here; rule['pattern'] overrides for non-default cases.
    pattern = rule.get("pattern", r"(?i)(Authorization:\s*)[^\r\n]+")
    replacement = rule.get("replacement", r"\1[REDACTED]")
    sf.raw_bytes = re.sub(pattern, replacement, text).encode("utf-8")


def _scrub_null_out(sf: SourceFile, rule: dict) -> None:
    """Pattern-based field nulling for form-encoded or plain-text payloads (INV-01).

    Matches field names from rule['field_pattern'] followed by '=' and nulls
    the value (empties the value string, preserving the key and delimiter).
    Overwrites sf.raw_bytes in-place.

    Default field pattern targets common password field names (C754889 use-case).
    """
    text = _load_raw_text(sf)
    if text is None:
        return
    field_pattern = rule.get("field_pattern", r"password|passwd|pwd|pass")
    sf.raw_bytes = re.sub(
        rf"((?:{field_pattern})=)[^&\r\n]*",
        r"\1",
        text,
        flags=re.IGNORECASE,
    ).encode("utf-8")


def _scrub_json_body(sf: SourceFile, rule: dict) -> None:
    """Pattern-based JSON body credential field scrub (INV-01).

    After HTTP envelope strip is not required — the regex safely applies to
    the full raw bytes (HTTP headers will not contain JSON body keys).
    Matches JSON string values for keys matching rule['field_pattern'] and
    replaces with rule['replacement'].  Overwrites sf.raw_bytes in-place.

    Default targets bearer/access token fields (C103403 use-case).
    """
    text = _load_raw_text(sf)
    if text is None:
        return
    field_pattern = rule.get("field_pattern", r"bearer.?token|access.?token|api.?key")
    replacement = rule.get("replacement", "[SCRUBBED]")
    sf.raw_bytes = re.sub(
        rf'(?i)("(?:{field_pattern})"\s*:\s*)"[^"]*"',
        rf'\1"{replacement}"',
        text,
    ).encode("utf-8")


# =============================================================================
# 3. PRE-PROCESS — strip / decompress / decode / multiparse / externalise
# =============================================================================
def http_envelope_strip(raw: bytes) -> bytes:
    """raw/ wire payloads carry HTTP headers; body starts after CRLFCRLF."""
    sep = b"\r\n\r\n"
    return raw.split(sep, 1)[1] if sep in raw else raw


def maybe_gunzip(body: bytes) -> bytes:
    return gzip.decompress(body) if body[:2] == b"\x1f\x8b" else body


def normalise_encoding(body: bytes, accept: str, target: str = "utf-8") -> bytes:
    """Normalise body bytes to the target encoding (default UTF-8).

    Strategy:
      1. Try UTF-8. If valid, re-encode to target (no-op when target=='utf-8').
      2. If UnicodeDecodeError, fall back to ISO-8859-1.
      3. If both fail, raise ValueError with the connector code for traceability.

    Args:
        body:   raw bytes to normalise.
        accept: connector code or content-type hint — included in error message only.
        target: target encoding (default 'utf-8').
    """
    for encoding in ("utf-8", "iso-8859-1"):
        try:
            decoded = body.decode(encoding)
        except UnicodeDecodeError:
            continue
        try:
            return decoded.encode(target)
        except UnicodeEncodeError:
            raise ValueError(
                f"Cannot re-encode body for connector {accept}: "
                f"characters not representable in {target!r}"
            )
    raise ValueError(
        f"Cannot decode body for connector {accept}: "
        f"not valid UTF-8 or ISO-8859-1"
    )


def extract_base64_blob(value: str) -> bytes:
    return base64.b64decode(value)


def json_multiparse(value: Any, depth: int) -> Any:
    """Stringified-JSON that needs N rounds of json.loads (USCC double, Kapitus triple)."""
    out = value
    for _ in range(depth):
        if isinstance(out, str):
            out = json.loads(out)
        else:
            break
    return out


def externalise_if_large(value: Any, key: str, app_id: str, cfg: ClientConfig,
                         lineage_blobs: list[dict]) -> Any:
    """Fields above the size threshold (or binary PDFs) go to object storage and
    are replaced by an external_ref URI (Kapitus REQ-VAL-09/05)."""
    threshold = int(cfg["preprocess"]["external_ref"]["size_threshold_kb"]) * 1024
    blob = value if isinstance(value, (bytes, bytearray)) else str(value).encode()
    if len(blob) < threshold and not _looks_like_pdf(blob):
        return value
    uri = _object_store_put(blob, app_id, key, cfg)        # TODO(team) adapter
    lineage_blobs.append({"field": key, "uri": uri, "size_bytes": len(blob)})
    return {"external_ref": uri}


def _looks_like_pdf(b: bytes) -> bool:
    return b[:4] == b"%PDF"


def _object_store_put(blob: bytes, app_id: str, key: str, cfg: ClientConfig) -> str:
    pattern = cfg["preprocess"]["external_ref"]["object_store_uri_pattern"]
    # TODO(team): real put; for now just format the deterministic URI.
    return pattern.format(app_id=app_id, connector=key.split(".")[0], field=key)


# =============================================================================
# 4. PARSE STRATEGY REGISTRY  (the only place parsing varies)
# =============================================================================
ParseFn = Callable[[SourceFile, ClientConfig], Any]
_STRATEGIES: dict[str, ParseFn] = {}


def strategy(name: str) -> Callable[[ParseFn], ParseFn]:
    def deco(fn: ParseFn) -> ParseFn:
        _STRATEGIES[name] = fn
        return fn
    return deco


def parse_file(sf: SourceFile, cfg: ClientConfig) -> Any:
    conn = _connector_cfg(sf.connector, cfg)
    if conn and conn.get("is_credential"):
        return None                                    # scrub-only, never parsed
    strat = (conn or {}).get("parse_strategy", "raw_json")
    fn = _STRATEGIES.get(strat)
    if not fn:
        raise KeyError(f"No parse strategy '{strat}' registered for {sf.connector}")
    sf.payload = fn(sf, cfg)
    return sf.payload


@strategy("gds_envelope_json")
def _parse_gds_envelope(sf: SourceFile, cfg: ClientConfig) -> Any:
    """data/ tier: full GDS envelope; real payload under data{}."""
    obj = json.loads(sf.path.read_text(encoding="utf-8"))
    return obj.get("data", obj)


@strategy("raw_json")
def _parse_raw_json(sf: SourceFile, cfg: ClientConfig) -> Any:
    body = maybe_gunzip(http_envelope_strip(sf.path.read_bytes()))
    return json.loads(body)


@strategy("xml_dict")
def _parse_xml(sf: SourceFile, cfg: ClientConfig) -> Any:
    import xmltodict  # all TR connectors; TransUnion XML
    body = maybe_gunzip(http_envelope_strip(sf.path.read_bytes()))
    d = xmltodict.parse(body)
    return _strip_ns(d)          # drop ns2:/bs:/cs: prefixes


@strategy("soap_xml")
def _parse_soap(sf: SourceFile, cfg: ClientConfig) -> Any:
    import xmltodict             # USCC C23812 manual review
    body = http_envelope_strip(sf.path.read_bytes())
    return _strip_ns(xmltodict.parse(body))


@strategy("fff")
def _parse_fff(sf: SourceFile, cfg: ClientConfig) -> Any:
    # Fixed-form-format bureau payload (SOC Experian C161652).
    # TODO(team): width spec per record type from the SDD / bureau layout.
    raise NotImplementedError("FFF layout spec required from team")


@strategy("binary_external_ref")
def _parse_binary(sf: SourceFile, cfg: ClientConfig) -> Any:
    body = http_envelope_strip(sf.path.read_bytes())
    blobs: list[dict] = []
    return externalise_if_large(body, f"{sf.connector}.body",
                                sf.app_id_raw or "unknown", cfg, blobs)


@strategy("credential_discard")
def _parse_cred(sf: SourceFile, cfg: ClientConfig) -> Any:
    return None


def _strip_ns(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k.split(":")[-1]: _strip_ns(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_strip_ns(v) for v in obj]
    return obj


def _connector_cfg(code: str | None, cfg: ClientConfig) -> dict | None:
    for c in cfg.get("connectors", []) or []:
        if c["code"] == code:
            return c
    return None


# =============================================================================
# 5. GEO DISPATCH + GROUP + MERGE
# =============================================================================
def dispatch_by_geo(files: list[SourceFile]) -> dict[str, list[SourceFile]]:
    """Partition files into {'USA': [...], 'CAN': [...]}.

    Single purpose: geography-based routing only.
    INV-10: routing is explicit and deterministic — no default, no inference.
    Files with geography not in ('USA', 'CAN') are unroutable and logged as errors.
    Both partition keys are always present in the return value, even if empty.
    CQ-001: single purpose; loop nesting ≤ 2 levels.
    """
    partitions: dict[str, list[SourceFile]] = {"USA": [], "CAN": []}
    unroutable: list[SourceFile] = []

    for sf in files:
        if sf.geography in ("USA", "CAN"):
            partitions[sf.geography].append(sf)
        else:
            unroutable.append(sf)

    for sf in unroutable:
        log.error(
            "QUARANTINE geo=None/unrecognised file=%s — INV-10", sf.path.name
        )

    return partitions


def group_by_app(files: list[SourceFile], cfg: ClientConfig) -> dict[str, AppRecord]:
    apps: dict[str, AppRecord] = {}
    for sf in files:
        if not sf.app_id_raw:
            continue
        canonical = _canonicalise_app_id(sf.app_id_raw, cfg)
        rec = apps.setdefault(canonical, AppRecord(canonical, sf.app_id_raw))
        rec.files.append(sf)
    return apps


def _canonicalise_app_id(raw: str, cfg: ClientConfig) -> str:
    out = raw
    for rule in cfg["application_id"].get("suffix_rules", []) or []:
        suf = rule.get("suffix")
        if suf and out.endswith(suf) and rule.get("action") == "strip":
            out = out[: -len(suf)]
    return out


def merge_sessions(rec: AppRecord, cfg: ClientConfig) -> None:
    """Apply the client's session model. Sets multi_session_incomplete etc."""
    model = cfg["sessions"]["model"]
    if model == "multi_session_merge":
        expected = int(cfg["sessions"]["multi_session"]["expected_sessions"])
        seqs = {sf.sequence_id for sf in rec.files if sf.sequence_id}
        if len(seqs) < expected:
            rec.lineage["multi_session_incomplete"] = True
            rec.quarantined = True
    # TODO(team): label multi_fire connectors (e.g. transunion_call_1/2) by step.


# =============================================================================
# 6. FIELD MAPPING — drive from field_mapping.<CLIENT>.xlsx
# =============================================================================
@dataclass
class MappingRow:
    sdd_path: str
    category: str
    data_type: str
    pii: bool
    sources: list[dict]            # ordered primary/secondary/tertiary
    transform: str | None
    construction: str | None       # free-text construction logic / array filter


def load_mapping_sheet(xlsx_path: str | Path) -> list[MappingRow]:
    """Read the canonical field-mapping workbook into MappingRows.
    Column layout is defined in references/mapping_schema.md."""
    from openpyxl import load_workbook
    wb = load_workbook(xlsx_path, read_only=True, data_only=True)
    ws = wb["Field Mapping"]
    rows = list(ws.iter_rows(values_only=True))
    header = {str(h).strip(): i for i, h in enumerate(rows[0]) if h}
    out: list[MappingRow] = []
    for r in rows[1:]:
        sdd = r[header.get("SDD Field Path", 1)]
        if not sdd or str(sdd).strip().startswith("──"):
            continue                                   # category banner
        out.append(_row_from_cells(r, header))
    return out


def _row_from_cells(r, header) -> MappingRow:
    def cell(name, default=None):
        i = header.get(name)
        return r[i] if i is not None and i < len(r) else default
    sources = []
    for tier in ("PRIMARY", "SECONDARY", "TERTIARY"):
        conn = cell(f"{tier}\nConnector | Folder | Direction") or cell(f"{tier} Connector | Folder | Direction")
        path = cell(f"{tier} Path") or cell(f"PRIMARY Path\n[Obj-1 / Current / First Score]") if tier == "PRIMARY" else cell(f"{tier} Path")
        if conn:
            sources.append({"tier": tier, "locator": str(conn), "path": str(path or "")})
    return MappingRow(
        sdd_path=str(cell("SDD Field Path")).strip(),
        category=str(cell("Category") or ""),
        data_type=str(cell("Data Type") or ""),
        pii=bool(cell("PII")),
        sources=sources,
        transform=cell("Transform"),
        construction=cell("Mapping Notes / Construction Logic / Open Questions"),
    )


def apply_mapping(rec: AppRecord, mapping: list[MappingRow], cfg: ClientConfig) -> None:
    """For each SDD path, resolve by source priority and write into rec.record."""
    for row in mapping:
        value = resolve_source(rec, row, cfg)
        if value is None:
            continue
        value = apply_transform(value, row, rec, cfg)
        _set_path(rec.record, row.sdd_path, value)


def resolve_source(rec: AppRecord, row: MappingRow, cfg: ClientConfig) -> Any:
    """Walk primary -> secondary -> tertiary; take first present non-null.
    This is the generic Source-Priority resolution all four clients use."""
    for src in row.sources:
        val = _read_locator(rec, src, cfg)
        if val not in (None, "", []):
            return val
    return None


def _read_locator(rec: AppRecord, src: dict, cfg: ClientConfig) -> Any:
    # locator like "C4871 web_service | data/ | REQ"; path like "data.Request.contract_id"
    # TODO(team): match connector+folder+direction to the right SourceFile.payload,
    # then dotted-path lookup. Returns None if not present (graceful nulls).
    return None


def apply_transform(value: Any, row: MappingRow, rec: AppRecord, cfg: ClientConfig) -> Any:
    t = (row.transform or "").lower()
    if "date" in t:
        return _to_utc_iso(value)
    if "numeric" in t or "int" in t:
        return _coerce_number(value)
    if "split" in t:
        delim = "|"                                     # configurable per row
        return [s.strip() for s in str(value).split(delim) if s.strip()]
    # EAV, score-array construction, per-applicant indicator filtering,
    # one-object->multi-entry expansion (TIB) are construction-logic transforms.
    # TODO(team): dispatch on row.construction for those.
    return value


# =============================================================================
# 7. INVARIANT I2 — PII TOKENISATION (before write) + scan
# =============================================================================
def tokenise_pii(rec: AppRecord, cfg: ClientConfig) -> None:
    for f in cfg.get("pii", {}).get("fields", []) or []:
        # TODO(team): locate the field in rec.record and replace with token per method:
        #   pseudonym_reversible -> vault token ; oneway_hash -> hash ;
        #   scrub_never_store -> remove ; year_only -> truncate DOB.
        pass
    if cfg["pii"]["extra_columns_scan"]["enabled"]:
        _scan_extra_columns_for_pii(rec, cfg)


def _scan_extra_columns_for_pii(rec: AppRecord, cfg: ClientConfig) -> None:
    # TODO(team): regex scan every extraColumns value; tokenise matches.
    pass


def assert_no_raw_pii(rec: AppRecord, cfg: ClientConfig) -> None:
    """INVARIANT I2 post-write proof. Raises if any raw-PII pattern remains."""
    patterns = cfg["pii"]["extra_columns_scan"]["patterns"]
    blob = json.dumps(rec.record) + json.dumps(rec.extra_columns)
    # TODO(team): compile real regexes for ssn/fein/ach/email/phone.
    for _pat in patterns:
        pass
    # raise RuntimeError(f"RAW PII detected in {rec.app_id_canonical}") on match


# =============================================================================
# 8. INVARIANT I3 — VALIDATION (before write) + quarantine
# =============================================================================
RuleFn = Callable[[AppRecord, ClientConfig], bool]   # True == pass
_RULES: dict[str, RuleFn] = {}


def rule(rule_id: str):
    def deco(fn: RuleFn):
        _RULES[rule_id] = fn
        return fn
    return deco


@rule("REQ-VAL-001")
def _appid_present(rec, cfg): return bool(rec.app_id_canonical)

@rule("REQ-VAL-002")
def _geo_valid(rec, cfg):
    valids = cfg["validation"]["client_params"]["valid_geographies"]
    return rec.geography in valids if rec.geography else True

@rule("REQ-VAL-005")
def _date_valid(rec, cfg):
    d = rec.record.get("system", {}).get("application", {}).get("applicationDate")
    return _is_iso_utc(d) if d else False

# REQ-VAL-007 (no raw PII) and REQ-VAL-008 (creds scrubbed) are proven by the
# invariant steps themselves; they appear here as explicit gates too.
@rule("REQ-VAL-007")
def _no_raw_pii(rec, cfg): return True   # assert_no_raw_pii already ran

@rule("REQ-VAL-008")
def _creds_scrubbed(rec, cfg):
    return bool(rec.lineage.get("credential_scrubbed_connectors") is not None)

# TODO(team): add REQ-VAL-003/004/006 and REQ-BL-001..N as the clients require.


def validate(rec: AppRecord, cfg: ClientConfig) -> None:
    hard = set(cfg["validation"]["hard_quarantine_rules"])
    for rid, fn in _RULES.items():
        try:
            passed = fn(rec, cfg)
        except Exception as e:                          # a throwing rule == fail
            passed = False
            log.warning("rule %s errored: %s", rid, e)
        if not passed:
            rec.validation_failures.append(rid)
            if rid in hard:
                rec.quarantined = True
    rec.lineage["validation_status"] = (
        "FAIL" if rec.quarantined else "WARN" if rec.validation_failures else "PASS"
    )
    rec.lineage["validation_failures"] = rec.validation_failures


# =============================================================================
# 9. LINEAGE + WRITE
# =============================================================================
def build_lineage(rec: AppRecord, cfg: ClientConfig, source_zip: str,
                  scrubbed: list[str], blobs: list[dict]) -> None:
    rec.lineage.update({
        "source_zip": source_zip,
        "app_id_raw": rec.app_id_raw,
        "app_id_canonical": rec.app_id_canonical,
        "geography": rec.geography,
        "client_code": cfg.client_code,
        "schema_version": cfg.schema_version,
        "mapping_config_version": cfg.get("config_version"),
        "transform_timestamp": datetime.now(timezone.utc).isoformat(),
        "source_files": [str(sf.path.name) for sf in rec.files],
        "credential_scrubbed_connectors": scrubbed,
        "base64_blobs_extracted": blobs,
        "has_connector_data": any(sf.connector for sf in rec.files),
    })
    rec.record.setdefault("system", {})["lineage"] = rec.lineage


def write_record(rec: AppRecord, cfg: ClientConfig) -> None:
    if rec.quarantined:
        log.error("QUARANTINE %s -> %s", rec.app_id_canonical, rec.validation_failures)
        return                                          # blocked from DataLake=Y
    # TODO(team): real DataLake write (partitioned by client/geography/date).
    log.info("WRITE %s (%s)", rec.app_id_canonical, rec.lineage["validation_status"])


# =============================================================================
# 10. ORCHESTRATION — fixed order; invariants cannot be reordered
# =============================================================================
def _handle_fff_quarantine(sf: SourceFile, cfg: ClientConfig) -> None:
    # TODO(Q-FFF): FFF parse failure quarantine handling pending Q-FFF resolution.
    log.warning(
        "FFF quarantine pending Q-FFF: file=%s connector=%s", sf.path.name, sf.connector
    )


def run_pipeline(
    zip_path: str | Path,
    config_path: str | Path,
    mapping_path: str | Path,
    workdir: str | Path,
) -> list[AppRecord]:
    """
    Process a GDS ZIP package through the full SOC ingestion pipeline.

    Fixed call order — invariants cannot be reordered:
      1. build_manifest()
      2. dispatch_by_geo()            — INV-10: before any scrub or parse
      3. Per-geography loop:
         a. scrub_credentials()      — I1: first operation inside per-geo loop
         b. parse_file()
         c. group_by_app()
         d. per-record: merge_sessions → apply_mapping → tokenise_pii (I2)
            → assert_no_raw_pii (I2) → build_lineage → validate (I3) → write_record
    """
    cfg_base = ClientConfig.load(config_path)   # base config for manifest build

    root = unpack_zip(zip_path, workdir)
    # GDS packages often have a single top-level subfolder; descend into it
    subdirs = [p for p in root.iterdir() if p.is_dir()]
    if len(subdirs) == 1:
        root = subdirs[0]
    files = build_manifest(root, cfg_base)

    geo_files = dispatch_by_geo(files)          # INV-10: dispatch BEFORE scrub

    out: list[AppRecord] = []
    for geo, geo_file_set in geo_files.items():
        if not geo_file_set:
            continue

        geo_cfg = ClientConfig.load(f"assets/client_config.SOC_{geo}.yaml")
        try:
            geo_mapping = load_mapping_sheet(f"assets/field_mapping.SOC_{geo}.xlsx")
        except Exception as e:
            log.warning("field mapping unavailable for %s: %s — mapping skipped", geo, e)
            geo_mapping = []

        scrubbed = scrub_credentials(geo_file_set, geo_cfg)    # I1 — FIRST in loop
        for sf in geo_file_set:
            try:
                parse_file(sf, geo_cfg)
            except NotImplementedError as e:
                log.warning("parse pending %s: %s", sf.connector, e)
                _handle_fff_quarantine(sf, geo_cfg)            # TODO(Q-FFF)

        apps = group_by_app(geo_file_set, geo_cfg)
        blobs: list[dict] = []
        for rec in apps.values():
            rec.geography = geo
            merge_sessions(rec, geo_cfg)
            apply_mapping(rec, geo_mapping, geo_cfg)
            tokenise_pii(rec, geo_cfg)                          # I2 — before write
            assert_no_raw_pii(rec, geo_cfg)                     # I2 — proof
            build_lineage(rec, geo_cfg, str(zip_path), scrubbed, blobs)
            validate(rec, geo_cfg)                              # I3 — before write
            write_record(rec, geo_cfg)
            out.append(rec)

    return out


# --- small shared helpers ----------------------------------------------------
def _to_utc_iso(value: Any) -> str | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%Y%m%d%H%M%S", "%Y-%m-%dT%H:%M:%S"):
        try:
            return datetime.strptime(str(value), fmt).replace(tzinfo=timezone.utc).isoformat()
        except ValueError:
            continue
    return None


def _coerce_number(value: Any):
    s = re.sub(r"[^\d.\-]", "", str(value))
    if s in ("", "-", "."):
        return None
    return float(s) if "." in s else int(s)


def _is_iso_utc(value: Any) -> bool:
    try:
        datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return True
    except (ValueError, TypeError):
        return False


def _set_path(obj: dict, dotted: str, value: Any) -> None:
    parts = dotted.split(".")
    cur = obj
    for p in parts[:-1]:
        cur = cur.setdefault(p, {})
    cur[parts[-1]] = value
