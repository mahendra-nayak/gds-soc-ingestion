"""
run_and_report.py
Run from repo root:
    python scripts/run_and_report.py
"""
from pathlib import Path
import json, sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from scripts.ingest_lib import run_pipeline

ZIP     = 'tests/fixtures/soc_sample.zip'
CFG_USA = 'assets/client_config.SOC_USA.yaml'
MAP_USA = 'assets/field_mapping.SOC_USA.xlsx'
WORKDIR = Path('run_output')

print('Running pipeline...')
result = run_pipeline(ZIP, CFG_USA, MAP_USA, WORKDIR)

# ── Quarantine report ─────────────────────────────────────────────────────────
report_path = WORKDIR / 'quarantine' / 'report.json'
if report_path.exists():
    r = json.loads(report_path.read_text())
    print('\n── Quarantine Report ─────────────────────')
    print(f'  total_records      : {r.get("total_records")}')
    print(f'  total_quarantined  : {r.get("total_quarantined")}')
    print(f'  quarantine_rate_pct: {r.get("quarantine_rate_pct")}')
    print(f'  reason_frequency   : {r.get("reason_frequency")}')
else:
    print('\n✗ report.json not found')

# ── Output records ────────────────────────────────────────────────────────────
usa_dir = WORKDIR / 'output' / 'USA'
can_dir = WORKDIR / 'output' / 'CAN'
usa_files = list(usa_dir.glob('*.json')) if usa_dir.exists() else []
can_files = list(can_dir.glob('*.json')) if can_dir.exists() else []

print('\n── DataLake=Y Output ─────────────────────')
print(f'  USA records: {len(usa_files)}')
for f in usa_files:
    print(f'    {f.name}')
print(f'  CAN records: {len(can_files)}')
for f in can_files:
    print(f'    {f.name}')

# ── Quarantine details ────────────────────────────────────────────────────────
q_dir = WORKDIR / 'quarantine'
q_files = [f for f in q_dir.glob('*.json') if f.name != 'report.json'] if q_dir.exists() else []
print(f'\n── Quarantined Records ({len(q_files)}) ──────────────')
for f in q_files:
    try:
        rec = json.loads(f.read_text())
        reasons = rec.get('quarantine_reason', [])
        print(f'  {f.stem:40} reasons={reasons}')
    except Exception:
        print(f'  {f.stem}  (unreadable)')

# ── AppRecord summary ─────────────────────────────────────────────────────────
print(f'\n── AppRecord Summary ({len(result)} total) ───────────')
for rec in result:
    status = rec.lineage.get('validation_status', '?')
    q_flag = '✗ QUARANTINED' if rec.quarantined else '✓'
    print(f'  {q_flag} {rec.app_id_canonical:40} geo={rec.geography} status={status}')
