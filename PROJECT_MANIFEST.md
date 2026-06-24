# PROJECT_MANIFEST.md
# Authoritative file registry for the SOC ingestion pipeline.
# All files read by the engine as authoritative input must be registered here.
# Last updated: 2026-06-24 · Session 1

---

## Engine

| File | Role | Status |
|---|---|---|
| `scripts/ingest_lib.py` | Pipeline engine (extend; do not fork) | Active |

---

## Configuration (structural validation only — no `<FILL:>` population by CC)

| File | Role | Status |
|---|---|---|
| `assets/client_config_template.yaml` | Config template | Active |
| `assets/client_config.SOC_USA.yaml` | USA pipeline config | Pending — FILL IN TASK-3/5 |
| `assets/client_config.SOC_CAN.yaml` | CAN pipeline config | Pending — FILL IN TASK-3/6 |
| `assets/field_mapping.SOC_USA.xlsx` | USA field mapping sheet | Pending — engineer-placed |
| `assets/field_mapping.SOC_CAN.xlsx` | CAN field mapping sheet | Pending — engineer-placed |

---

## References (read-only)

| File | Role | Status |
|---|---|---|
| `references/mapping_schema.md` | Parse strategy & transform contract | Active |

---

## Documentation

| File | Role | Status |
|---|---|---|
| `ARCHITECTURE.md` | System architecture | Active |
| `EXECUTION_PLAN.md` | Phased execution plan | Active |
| `INVARIANTS.md` | Hard invariant definitions | Active |
| `Claude.md` | CC instructions and scope boundary | Active |
| `README.md` | Project overview | Active |

---

## Tests

| File | Role | Status |
|---|---|---|
| `tests/fixtures/` | Sample fixtures (engineer-placed; not committed to Git) | Pending |
| `tests/unit/` | Unit test modules | Pending |
| `tests/integration/` | Integration test modules | Pending |

---

## Directory Structure

```
scripts/
assets/
references/
tests/
  fixtures/
  unit/
  integration/
docs/
sessions/
verification/
discovery/
tools/
```

---

## Registration Rules

- Any file read by CC as authoritative input must appear in this manifest.
- Files not listed here are not authoritative and must be flagged before use.
- Test fixture files in `tests/fixtures/` are engineer-placed and not committed to Git.
