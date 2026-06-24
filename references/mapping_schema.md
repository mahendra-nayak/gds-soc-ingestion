# references/mapping_schema.md — Parse Strategy & Transform Contract
# READ-ONLY REFERENCE. Do not modify this file.
# Authoritative source: PROJECT_MANIFEST.md

---

## 1. Parse Strategies

Each file in the manifest is assigned exactly one parse strategy.
The strategy is executed on the **scrubbed** text (post `scrub_credentials()`).

| Strategy | Input | Output | Notes |
|---|---|---|---|
| `gds_envelope_json` | JSON string with outer envelope | `dict` (inner payload) | Unwraps `payload`/`data`/`body`/`content` key |
| `raw_json` | Raw JSON string | `dict` | No envelope stripping |
| `xml_dict` | XML string | `dict` | Via `xmltodict` |
| `soap_xml` | SOAP XML string | `dict` | Unwraps `Envelope > Body > first child` |
| `fff` | FFF flat-file string | `dict` | **Stub only — raises `NotImplementedError`. Gated on Q-FFF.** |
| `binary_external_ref` | Binary/opaque bytes | `dict` with ref stub | Content not parsed inline |
| `credential_discard` | Credential-only payload | `dict` discard marker | No content logged or stored — IC-1/IC-4 |

---

## 2. Transforms

Transforms are applied via `apply_transform(name, value, params)` during field mapping.

| Transform | Input | Output | Key Params |
|---|---|---|---|
| `date_to_utc_iso` | Date string | UTC ISO-8601 string | `fmt` (strptime format, default `%Y-%m-%d`) |
| `string_to_numeric` | Numeric string | `int` or `float` | `numeric_type`: `"int"` \| `"float"` (default `"float"`) |
| `split_on_delim` | Delimited string | `list[str]` | `delim` (default `,`) |
| `json_double_parse` | Double-encoded JSON string | parsed object | — |
| `ast_literal_eval` | Python repr string | Python literal | Uses `ast.literal_eval()` — `eval()` is prohibited |
| `base64_extract` | Base64 string | Decoded string | `encoding` (default `utf-8`) |

---

## 3. Invariant Checkpoints

| Checkpoint | Function | Stage |
|---|---|---|
| IC-1 | `scrub_credentials()` | Before any parse/log/route |
| IC-2a | `tokenise_pii()` | After parse, before write |
| IC-2b | `assert_no_raw_pii()` | Inside `write_record()` — write gate |
| IC-2c | `validate()` | After tokenise, before write |
| IC-3 | `normalise_app_id()` + `build_lineage()` | At AppRecord construction |
| IC-4 | `scrub_credentials()` + `credential_discard` strategy | Before any persistence |
| IC-5 | `tokenise_pii()` + `assert_no_raw_pii()` | Before DataLake=Y write |

---

## 4. AppRecord ID Rules (IC-3)

- `app_id_raw`: original value from source, **including** `_test` suffix if present. Always `str`.
- `app_id_canonical`: `app_id_raw` with `_test` suffix stripped. Always `str`.
- `debtor_number`, `sequence_id`: always `str`. Never cast to `int`, `bigint`, or any numeric type.
- Both `app_id_raw` and `app_id_canonical` must appear in `lineage` on every output record.

---

## 5. DataLake Write Gate

`write_record()` will raise `RuntimeError` if called before:
- `tokenise_pii()` has set `record._pii_tokenised = True`, **and**
- `validate()` has set `record._validated = True`

`write_record()` internally calls `assert_no_raw_pii()` as a final write gate.
A record that fails this gate must never reach `data_lake_flag = "Y"`.
