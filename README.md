# gds-soc-ingestion

SOC ingestion pipeline — converts raw GDS ZIP packages into standardised, PII-clean, credential-scrubbed, validated JSON records per Application ID, aligned to Standard Schema v1.1, ready for DataLake write.

**Project:** PBVI DATA_ACCELERATOR
**Engine:** `scripts/ingest_lib.py`
**Schema version:** v1.1

---

## Phase Status

| Phase | Description | Status |
|---|---|---|
| Phase 1 | Discovery & Column Mapping | Complete |
| Phase 2 | Architecture & Invariant Design | Complete |
| Phase 3 | Specification & Config | Complete |
| Phase 4 | Gate Record | Passed |
| Session 1 | Project Scaffold + Pipeline Spine | In Progress |
| Session 2 | Field Mapping & Transform Layer | Pending |
| Session 3 | Connector Credential Handling | Pending |
| Session 4 | Validation & Quarantine | Pending |
| Session 5 | DataLake Write + Integration Tests | Pending |

---

## Repository Structure

```
scripts/          — pipeline engine
assets/           — config files and field mapping sheets
references/       — read-only reference documents
tests/
  fixtures/       — sample fixtures (engineer-placed; not committed)
  unit/           — unit tests
  integration/    — integration tests
docs/             — architecture and phase gate records
sessions/         — session working notes
verification/     — verification outputs
discovery/        — discovery artefacts
tools/            — tooling scripts
```

---

## Invariants

All pipeline invariants are defined in `INVARIANTS.md` and enforced in `scripts/ingest_lib.py`.
No invariant may be removed or bypassed. See `Claude.md` for scope boundary.
