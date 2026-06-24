# Mapping & Config Schema — Reference

Read this when filling a client config, adding a parse strategy, or extending the
field-mapping sheet. The engine (`scripts/ingest_lib.py`) is the source of truth
for behaviour; this doc explains the contract.

---

## The two per-client artifacts

| Artifact | Format | Holds | Read by |
|---|---|---|---|
| `client_config.<CLIENT>.yaml` | YAML | structure: connectors, folders + priority, app-id rule, session model, preprocess, pii methods, decision source, validation toggles, extra-columns groups | `ClientConfig.load` |
| `field_mapping.<CLIENT>.xlsx` | xlsx | one row per SDD path → primary/secondary/tertiary source + transform + PII/cred disposition | `load_mapping_sheet` |

Keep them in sync: every connector named in the mapping sheet's locators must
exist in the config's `connectors:` list; every PII-flagged path must appear in
config `pii.fields`.

### Why two files, not one

Structure (which connectors exist, how sessions merge, where credentials live)
is small, changes rarely, and is best reviewed as code → YAML. The 242-path
field mapping is large, edited by analysts, and benefits from a grid → xlsx.
This also matches how the teams already work: SOC kept a YAML
(`ConnectorMappingConfig_SOC.yaml`); USCC, Kapitus and TIB kept xlsx mapping
sheets. This schema unifies both.

---

## Parse strategies (registry in the engine)

`connectors[].parse_strategy` must name one of these. Add new ones with the
`@strategy("name")` decorator — never branch on client inside a strategy.

| Strategy | Wire format | Notes / seen at |
|---|---|---|
| `gds_envelope_json` | GDS-JSON (`data/`) | payload under `data{}`. All clients' `data/` tier. |
| `raw_json` | HTTP+JSON (`raw/`) | HTTP strip + auto-gunzip then `json.loads`. USCC/Kapitus bureau JSON. |
| `xml_dict` | HTTP+XML | `xmltodict` + namespace strip. TransUnion (USCC C25755), all Kapitus TR. |
| `soap_xml` | SOAP/XML | USCC manual review C23812 (scrub `uscSecurityToken` first). |
| `fff` | fixed-form | SOC Experian C161652. Needs width spec from team. |
| `binary_external_ref` | HTTP+PDF / multipart | detect `%PDF` → object storage → `external_ref`. Kapitus C628492/C702265/C410135. |
| `credential_discard` | any | `is_credential: true` connectors. Never produces a payload. |

---

## Transforms (dispatch on `field_mapping.Transform`)

| Transform | Meaning |
|---|---|
| `date_to_utc_iso` | parse heterogeneous date → ISO-8601 UTC |
| `string_to_numeric` | strip non-numerics → int/float (scores `'552'`→`552`) |
| `split_on_delim` | pipe/etc-delimited string → array (`Dec_Reasons`, `Stipulations`) |
| `eav` | scalar → `{name, value}` entity-attribute-value (Kapitus summaries) |
| `score_array_construct` | flat `scoreN`+`ScoreN_name` → `scores[]` (USCC audit, up to 14) |
| `per_applicant_indicator_filter` | filter record-level array by `*_ApplicantIndicator` (TIB) |
| `one_object_to_multi_entry` | one source object → many SS list entries: current/previous/mailing (TIB) |
| `external_ref_if_large` | > size threshold or binary → object storage URI (Kapitus REQ-VAL-05/09) |
| `json_double_parse` / `json_triple_parse` | stringified-JSON N-deep (USCC C23612 / Kapitus C373382) |
| `base64_extract` | decode base64 blob then parse (SOC C103403) |

---

## The three invariants (engine-enforced)

| # | Invariant | Where |
|---|---|---|
| I1 | Credential scrub runs first | `run_pipeline` calls `scrub_credentials` before any parse/log |
| I2 | PII tokenised before write + post-write zero-raw-PII assertion | `tokenise_pii` → `assert_no_raw_pii` |
| I3 | Validation before write; hard-quarantine failures block | `validate` → `write_record` |

Config can declare where credentials/PII are; it cannot move when these run.

---

## Validation rule library

Rules register with `@rule("REQ-VAL-00X")` / `@rule("REQ-BL-00X")` and return
`True` on pass. Config only enables/parameterises them
(`validation.hard_quarantine_rules`, `validation.soft_warn_rules`,
`validation.client_params`). Shipped: REQ-VAL-001/002/005/007/008. Add the rest
(REQ-VAL-003/004/006, REQ-BL-*) as each client's doc requires — a throwing rule
counts as a fail, so rules can assume well-formed input and raise otherwise.

---

## Lineage fields emitted on every record

`source_zip`, `app_id_raw`, `app_id_canonical`, `geography`, `client_code`,
`schema_version`, `mapping_config_version`, `transform_timestamp`,
`source_files[]`, `credential_scrubbed_connectors[]`, `base64_blobs_extracted[]`,
`has_connector_data`, `validation_status`, `validation_failures[]`
(+ `multi_session_incomplete` when the session model applies).

These are what make cross-client comparison auditable:
filter to identical `schema_version` + `mapping_config_version` before any
field-level comparison.

---

## Cross-client safety

Core Standard Schema paths are comparable across clients; everything else lands
under the client's `extension_namespace` in `extraColumns{}` and must be
excluded from cross-client queries. Decision codes are comparable only after
`decision.code_normalisation` maps them to the shared vocabulary
(`APPROVED`/`DECLINED`/`REVIEW`/`ERROR`/`INCOMPLETE`). Never join on raw App IDs
or raw PII across clients.
