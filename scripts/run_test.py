import sys, json, os, pathlib
sys.path.insert(0, 'scripts')
import ingest_lib as L
import logging

logging.basicConfig(level=logging.WARNING, format='%(levelname)s %(message)s')
os.chdir(r'C:\Users\nayak\OneDrive\Desktop\soc')

recs = L.run_pipeline(
    'tests/fixtures/soc_sample.zip',
    'assets/client_config.SOC_USA.yaml',
    'assets/field_mapping.SOC_USA.xlsx',
    'run_output_v2',
)

quarantined = [r for r in recs if r.quarantined]
print(f'Total: {len(recs)}, quarantined: {len(quarantined)}')

for r in recs:
    status = 'QUARANTINE' if r.quarantined else 'OK'
    print(f'  [{status}] {r.app_id_canonical} geo={r.geography} failures={r.validation_failures}')

out_files = list(pathlib.Path('run_output_v2/output').rglob('*.json'))
print(f'\nOutput files: {len(out_files)}')
for f in out_files:
    print(f'  {f.relative_to("run_output_v2/output")}')

report_path = pathlib.Path('run_output_v2/quarantine/report.json')
if report_path.exists():
    report = json.loads(report_path.read_text())
    print(f'\nQuarantine report:')
    print(f'  total_records:     {report["total_records"]}')
    print(f'  total_quarantined: {report["total_quarantined"]}')
    print(f'  quarantine_rate:   {report["quarantine_rate_pct"]}%')
    print(f'  reason_frequency:  {report["reason_frequency"]}')
